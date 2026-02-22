"""Tests for ExecutionRouter: route MCP tool calls -> apcore Executor pipeline."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from apcore_mcp.helpers import MCP_ELICIT_KEY, MCP_PROGRESS_KEY
from apcore_mcp.server.router import ExecutionRouter

# ---------------------------------------------------------------------------
# Stub error classes that mimic apcore error hierarchy for testing.
# Same pattern used in tests/adapters/test_errors.py.
# ---------------------------------------------------------------------------


class StubModuleError(Exception):
    """Base stub for apcore ModuleError."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}


class ModuleNotFoundStubError(StubModuleError):
    """Stub for apcore ModuleNotFoundError."""

    def __init__(self, module_id: str) -> None:
        super().__init__(
            code="MODULE_NOT_FOUND",
            message=f"Module not found: {module_id}",
            details={"module_id": module_id},
        )


class SchemaValidationStubError(StubModuleError):
    """Stub for apcore SchemaValidationError."""

    def __init__(
        self,
        message: str = "Schema validation failed",
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            code="SCHEMA_VALIDATION_ERROR",
            message=message,
            details={"errors": errors or []},
        )


class ACLDeniedStubError(StubModuleError):
    """Stub for apcore ACLDeniedError."""

    def __init__(self, caller_id: str | None, target_id: str) -> None:
        super().__init__(
            code="ACL_DENIED",
            message=f"Access denied: {caller_id} -> {target_id}",
            details={"caller_id": caller_id, "target_id": target_id},
        )


class CallDepthExceededStubError(StubModuleError):
    """Stub for apcore CallDepthExceededError."""

    def __init__(self, depth: int, max_depth: int, call_chain: list[str]) -> None:
        super().__init__(
            code="CALL_DEPTH_EXCEEDED",
            message=f"Call depth {depth} exceeds maximum {max_depth}",
            details={"depth": depth, "max_depth": max_depth, "call_chain": call_chain},
        )


class CircularCallStubError(StubModuleError):
    """Stub for apcore CircularCallError."""

    def __init__(self, module_id: str, call_chain: list[str]) -> None:
        super().__init__(
            code="CIRCULAR_CALL",
            message=f"Circular call detected for module {module_id}",
            details={"module_id": module_id, "call_chain": call_chain},
        )


class CallFrequencyExceededStubError(StubModuleError):
    """Stub for apcore CallFrequencyExceededError."""

    def __init__(self, module_id: str, count: int, max_repeat: int, call_chain: list[str]) -> None:
        super().__init__(
            code="CALL_FREQUENCY_EXCEEDED",
            message=f"Module {module_id} called {count} times, max is {max_repeat}",
            details={
                "module_id": module_id,
                "count": count,
                "max_repeat": max_repeat,
                "call_chain": call_chain,
            },
        )


# ---------------------------------------------------------------------------
# Stub executor for testing
# ---------------------------------------------------------------------------


class StubExecutor:
    """Stub executor that mimics apcore Executor.call_async()."""

    def __init__(
        self,
        results: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._results: dict[str, Any] = results or {}
        self._error = error
        self.calls: list[tuple[str, dict[str, Any] | None, Any]] = []

    async def call_async(
        self,
        module_id: str,
        inputs: dict[str, Any] | None = None,
        context: Any = None,
    ) -> Any:
        self.calls.append((module_id, inputs, context))
        if self._error:
            raise self._error
        if module_id in self._results:
            return self._results[module_id]
        raise ModuleNotFoundStubError(module_id)


class LegacyStubExecutor:
    """Stub executor that does NOT accept a context arg (backward compat)."""

    def __init__(
        self,
        results: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._results: dict[str, Any] = results or {}
        self._error = error
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def call_async(self, module_id: str, inputs: dict[str, Any] | None = None) -> Any:
        self.calls.append((module_id, inputs))
        if self._error:
            raise self._error
        if module_id in self._results:
            return self._results[module_id]
        raise ModuleNotFoundStubError(module_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExecutionRouter:
    """Test suite for ExecutionRouter."""

    @pytest.fixture
    def executor(self) -> StubExecutor:
        """Create a StubExecutor with a default result."""
        return StubExecutor(
            results={
                "image.resize": {"output_path": "/tmp/out.png", "new_size": [100, 100]},
            }
        )

    @pytest.fixture
    def router(self, executor: StubExecutor) -> ExecutionRouter:
        """Create an ExecutionRouter with the stub executor."""
        return ExecutionRouter(executor)

    async def test_handle_call_success(self, router: ExecutionRouter) -> None:
        """Successful execution returns JSON content with is_error=False."""
        content, is_error = await router.handle_call(
            "image.resize",
            {"width": 100, "height": 100, "image_path": "/tmp/in.png"},
        )

        assert is_error is False
        assert len(content) == 2  # result + trace_id
        assert content[0]["type"] == "text"

        # The text should be valid JSON containing the result
        parsed = json.loads(content[0]["text"])
        assert parsed["output_path"] == "/tmp/out.png"
        assert parsed["new_size"] == [100, 100]

        # Second content item should contain trace_id
        trace_meta = json.loads(content[1]["text"])
        assert "_trace_id" in trace_meta

    async def test_handle_call_success_json_serialization(self) -> None:
        """Output dict is properly JSON serialized with all types preserved."""
        result_data = {
            "string_val": "hello",
            "int_val": 42,
            "float_val": 3.14,
            "bool_val": True,
            "null_val": None,
            "list_val": [1, 2, 3],
            "nested": {"key": "value"},
        }
        executor = StubExecutor(results={"test.module": result_data})
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("test.module", {})

        assert is_error is False
        assert len(content) == 2  # result + trace_id
        parsed = json.loads(content[0]["text"])
        assert parsed == result_data

    async def test_handle_call_passes_arguments(self, router: ExecutionRouter, executor: StubExecutor) -> None:
        """Executor receives the correct tool_name and arguments."""
        arguments = {"width": 200, "height": 300, "image_path": "/tmp/photo.jpg"}
        await router.handle_call("image.resize", arguments)

        assert len(executor.calls) == 1
        call_module_id, call_inputs, call_context = executor.calls[0]
        assert call_module_id == "image.resize"
        assert call_inputs == arguments
        # Context is always created now
        assert call_context is not None

    async def test_handle_call_empty_arguments(self) -> None:
        """Works correctly with empty dict arguments."""
        executor = StubExecutor(results={"system.ping": {"status": "ok"}})
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("system.ping", {})

        assert is_error is False
        assert len(content) == 2  # result + trace_id
        parsed = json.loads(content[0]["text"])
        assert parsed["status"] == "ok"

        # Verify empty dict was passed through
        assert executor.calls[0][:2] == ("system.ping", {})

    async def test_handle_call_module_not_found(self) -> None:
        """MODULE_NOT_FOUND error returns error content with is_error=True."""
        executor = StubExecutor()  # No results -> ModuleNotFoundStubError
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("nonexistent.module", {})

        assert is_error is True
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert "nonexistent.module" in content[0]["text"]

    async def test_handle_call_schema_validation_error(self) -> None:
        """Schema validation errors return formatted validation message."""
        validation_errors = [
            {"field": "width", "message": "required"},
            {"field": "height", "message": "must be positive"},
        ]
        error = SchemaValidationStubError(
            "Validation failed",
            errors=validation_errors,
        )
        executor = StubExecutor(error=error)
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("image.resize", {"width": -1})

        assert is_error is True
        assert content[0]["type"] == "text"
        # ErrorMapper formats validation errors as "field: message; field: message"
        assert "width" in content[0]["text"]
        assert "height" in content[0]["text"]

    async def test_handle_call_acl_denied(self) -> None:
        """ACL denied returns sanitized 'Access denied' message, no caller leak."""
        error = ACLDeniedStubError("secret_user_42", "admin.delete")
        executor = StubExecutor(error=error)
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("admin.delete", {})

        assert is_error is True
        assert "access denied" in content[0]["text"].lower()
        # Must NOT leak the caller_id
        assert "secret_user_42" not in content[0]["text"]

    async def test_handle_call_internal_error_codes(self) -> None:
        """CALL_DEPTH_EXCEEDED, CIRCULAR_CALL, CALL_FREQUENCY_EXCEEDED return 'Internal error occurred'."""
        internal_errors = [
            CallDepthExceededStubError(10, 10, ["a", "b"]),
            CircularCallStubError("a", ["a", "b", "a"]),
            CallFrequencyExceededStubError("a", 5, 3, ["a"]),
        ]

        for error in internal_errors:
            executor = StubExecutor(error=error)
            router = ExecutionRouter(executor)

            content, is_error = await router.handle_call("some.module", {})

            assert is_error is True, f"{type(error).__name__} should set is_error=True"
            assert (
                "internal error" in content[0]["text"].lower()
            ), f"{type(error).__name__} should return 'Internal error occurred'"

    async def test_handle_call_unexpected_exception(self) -> None:
        """Non-apcore exceptions (no code/message/details) return generic 'Internal error occurred'."""
        error = RuntimeError("something broke badly in the internals")
        executor = StubExecutor(error=error)
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("some.module", {})

        assert is_error is True
        assert content[0]["text"] == "Internal error occurred"
        # Must NOT leak the original error message
        assert "something broke" not in content[0]["text"]

    async def test_handle_call_non_serializable_output(self) -> None:
        """Non-serializable types are handled via default=str fallback."""
        now = datetime(2025, 1, 15, 12, 30, 0)
        result_data = {
            "timestamp": now,
            "data": "normal string",
        }
        executor = StubExecutor(results={"time.now": result_data})
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("time.now", {})

        assert is_error is False
        assert len(content) == 2  # result + trace_id
        parsed = json.loads(content[0]["text"])
        # datetime should be converted to string via default=str
        assert parsed["timestamp"] == str(now)
        assert parsed["data"] == "normal string"

    async def test_handle_call_concurrent(self) -> None:
        """Multiple concurrent calls work correctly without interference."""
        results = {
            "module.a": {"result": "a"},
            "module.b": {"result": "b"},
            "module.c": {"result": "c"},
        }
        executor = StubExecutor(results=results)
        router = ExecutionRouter(executor)

        # Launch three concurrent calls
        tasks = [
            router.handle_call("module.a", {"id": "a"}),
            router.handle_call("module.b", {"id": "b"}),
            router.handle_call("module.c", {"id": "c"}),
        ]
        results_list = await asyncio.gather(*tasks)

        # All three should succeed
        for content, is_error in results_list:
            assert is_error is False
            assert len(content) == 2  # result + trace_id
            assert content[0]["type"] == "text"

        # Verify correct results were returned for each
        parsed_a = json.loads(results_list[0][0][0]["text"])
        parsed_b = json.loads(results_list[1][0][0]["text"])
        parsed_c = json.loads(results_list[2][0][0]["text"])

        assert parsed_a["result"] == "a"
        assert parsed_b["result"] == "b"
        assert parsed_c["result"] == "c"

        # All three calls should have been recorded
        assert len(executor.calls) == 3

    # ── New tests for context passing ────────────────────────────────────

    async def test_context_has_mcp_progress_when_extra_has_progress(self) -> None:
        """Context.data has _mcp_progress when extra has progress_token + send_notification."""
        executor = StubExecutor(results={"test.module": {"ok": True}})
        router = ExecutionRouter(executor)

        extra: dict[str, Any] = {
            "progress_token": "tok-1",
            "send_notification": AsyncMock(),
            "session": None,
        }

        await router.handle_call("test.module", {}, extra=extra)

        assert len(executor.calls) == 1
        _, _, context = executor.calls[0]
        assert context is not None
        assert MCP_PROGRESS_KEY in context.data
        assert callable(context.data[MCP_PROGRESS_KEY])

    async def test_context_has_mcp_elicit_when_extra_has_session(self) -> None:
        """Context.data has _mcp_elicit when extra has session."""
        executor = StubExecutor(results={"test.module": {"ok": True}})
        router = ExecutionRouter(executor)

        mock_session = AsyncMock()
        extra: dict[str, Any] = {
            "session": mock_session,
        }

        await router.handle_call("test.module", {}, extra=extra)

        assert len(executor.calls) == 1
        _, _, context = executor.calls[0]
        assert context is not None
        assert MCP_ELICIT_KEY in context.data
        assert callable(context.data[MCP_ELICIT_KEY])

    async def test_context_always_created_even_without_extra(self) -> None:
        """Context is always created, even when no extra is provided."""
        executor = StubExecutor(results={"test.module": {"ok": True}})
        router = ExecutionRouter(executor)

        await router.handle_call("test.module", {})

        assert len(executor.calls) == 1
        _, _, context = executor.calls[0]
        assert context is not None
        assert hasattr(context, "trace_id")
        assert context.trace_id is not None

    async def test_backward_compat_legacy_executor(self) -> None:
        """TypeError fallback when executor doesn't accept context arg."""
        executor = LegacyStubExecutor(results={"test.module": {"ok": True}})
        router = ExecutionRouter(executor)

        # Context is always created now, so legacy fallback always triggers
        content, is_error = await router.handle_call("test.module", {})

        assert is_error is False
        assert len(content) == 2  # result + trace_id
        parsed = json.loads(content[0]["text"])
        assert parsed == {"ok": True}
        # Legacy executor should still have been called
        assert len(executor.calls) == 1

    async def test_progress_callback_sends_notification(self) -> None:
        """The injected progress callback sends notifications/progress via send_notification."""
        received_context: list[Any] = []

        class CapturingExecutor:
            async def call_async(self, module_id: str, inputs: dict[str, Any], context: Any = None) -> Any:
                received_context.append(context)
                # Simulate module calling the progress callback
                if context and MCP_PROGRESS_KEY in context.data:
                    await context.data[MCP_PROGRESS_KEY](5, 10, "halfway")
                return {"done": True}

        executor = CapturingExecutor()
        router = ExecutionRouter(executor)

        send_notification = AsyncMock()
        extra: dict[str, Any] = {
            "progress_token": "tok-progress",
            "send_notification": send_notification,
        }

        content, is_error = await router.handle_call("test.module", {}, extra=extra)

        assert is_error is False
        assert len(content) == 2  # result + trace_id
        assert send_notification.call_count == 1
        notification = send_notification.call_args[0][0]
        assert notification["method"] == "notifications/progress"
        assert notification["params"]["progressToken"] == "tok-progress"
        assert notification["params"]["progress"] == 5
        assert notification["params"]["total"] == 10
        assert notification["params"]["message"] == "halfway"

    async def test_elicit_callback_calls_session_elicit_form(self) -> None:
        """The injected elicit callback calls session.elicit_form and returns result."""
        received_context: list[Any] = []

        class ElicitingExecutor:
            async def call_async(self, module_id: str, inputs: dict[str, Any], context: Any = None) -> Any:
                received_context.append(context)
                if context and MCP_ELICIT_KEY in context.data:
                    result = await context.data[MCP_ELICIT_KEY]("Confirm?", {"type": "object"})
                    return {"elicit_result": result}
                return {"no_elicit": True}

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.action = "accept"
        mock_result.content = {"confirmed": True}
        mock_session.elicit_form = AsyncMock(return_value=mock_result)

        executor = ElicitingExecutor()
        router = ExecutionRouter(executor)

        extra: dict[str, Any] = {"session": mock_session}

        content, is_error = await router.handle_call("test.module", {}, extra=extra)

        assert is_error is False
        assert len(content) == 2  # result + trace_id
        parsed = json.loads(content[0]["text"])
        assert parsed["elicit_result"]["action"] == "accept"
        assert parsed["elicit_result"]["content"] == {"confirmed": True}
        mock_session.elicit_form.assert_called_once_with(
            message="Confirm?",
            requestedSchema={"type": "object"},
        )

    async def test_elicit_callback_returns_none_on_error(self) -> None:
        """The injected elicit callback returns None when session.elicit_form raises."""
        received_context: list[Any] = []

        class ElicitingExecutor:
            async def call_async(self, module_id: str, inputs: dict[str, Any], context: Any = None) -> Any:
                received_context.append(context)
                if context and MCP_ELICIT_KEY in context.data:
                    result = await context.data[MCP_ELICIT_KEY]("Confirm?")
                    return {"elicit_result": result}
                return {"no_elicit": True}

        mock_session = AsyncMock()
        mock_session.elicit_form = AsyncMock(side_effect=RuntimeError("Connection lost"))

        executor = ElicitingExecutor()
        router = ExecutionRouter(executor)

        extra: dict[str, Any] = {"session": mock_session}

        content, is_error = await router.handle_call("test.module", {}, extra=extra)

        assert is_error is False
        assert len(content) == 2  # result + trace_id
        parsed = json.loads(content[0]["text"])
        assert parsed["elicit_result"] is None

    async def test_elicit_callback_default_schema(self) -> None:
        """The injected elicit callback passes empty dict when schema is None."""
        received_context: list[Any] = []

        class ElicitingExecutor:
            async def call_async(self, module_id: str, inputs: dict[str, Any], context: Any = None) -> Any:
                received_context.append(context)
                if context and MCP_ELICIT_KEY in context.data:
                    await context.data[MCP_ELICIT_KEY]("Confirm?", None)
                return {"ok": True}

        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.action = "decline"
        mock_result.content = None
        mock_session.elicit_form = AsyncMock(return_value=mock_result)

        executor = ElicitingExecutor()
        router = ExecutionRouter(executor)

        extra: dict[str, Any] = {"session": mock_session}

        await router.handle_call("test.module", {}, extra=extra)

        mock_session.elicit_form.assert_called_once_with(
            message="Confirm?",
            requestedSchema={},
        )

    # ── Tests for validate_inputs ────────────────────────────────────────

    async def test_validate_inputs_blocks_invalid(self) -> None:
        """validate_inputs=True rejects invalid inputs before execution."""
        from dataclasses import dataclass, field as dc_field

        @dataclass
        class ValidationResult:
            valid: bool
            errors: list[dict[str, str]] = dc_field(default_factory=list)

        class ValidatingExecutor:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, Any], Any]] = []

            def validate(self, module_id: str, inputs: dict[str, Any]) -> ValidationResult:
                return ValidationResult(
                    valid=False,
                    errors=[{"field": "width", "message": "required"}],
                )

            async def call_async(self, module_id: str, inputs: dict[str, Any], context: Any = None) -> Any:
                self.calls.append((module_id, inputs, context))
                return {"ok": True}

        executor = ValidatingExecutor()
        router = ExecutionRouter(executor, validate_inputs=True)

        content, is_error = await router.handle_call("image.resize", {})

        assert is_error is True
        assert "Validation failed" in content[0]["text"]
        assert "width: required" in content[0]["text"]
        # Executor should NOT have been called
        assert len(executor.calls) == 0

    async def test_validate_inputs_passes_valid(self) -> None:
        """validate_inputs=True allows valid inputs through to execution."""
        from dataclasses import dataclass, field as dc_field

        @dataclass
        class ValidationResult:
            valid: bool
            errors: list[dict[str, str]] = dc_field(default_factory=list)

        class ValidatingExecutor:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, Any], Any]] = []

            def validate(self, module_id: str, inputs: dict[str, Any]) -> ValidationResult:
                return ValidationResult(valid=True)

            async def call_async(self, module_id: str, inputs: dict[str, Any], context: Any = None) -> Any:
                self.calls.append((module_id, inputs, context))
                return {"ok": True}

        executor = ValidatingExecutor()
        router = ExecutionRouter(executor, validate_inputs=True)

        content, is_error = await router.handle_call("test.module", {"x": 1})

        assert is_error is False
        assert len(executor.calls) == 1

    async def test_validate_inputs_skips_when_executor_lacks_validate(self) -> None:
        """validate_inputs=True gracefully skips if executor has no validate()."""
        executor = StubExecutor(results={"test.module": {"ok": True}})
        router = ExecutionRouter(executor, validate_inputs=True)

        content, is_error = await router.handle_call("test.module", {})

        assert is_error is False
        parsed = json.loads(content[0]["text"])
        assert parsed == {"ok": True}

    async def test_validate_inputs_disabled_by_default(self) -> None:
        """validate_inputs defaults to False (no validation)."""
        executor = StubExecutor(results={"test.module": {"ok": True}})
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("test.module", {})

        assert is_error is False

    async def test_validate_inputs_handles_validate_exception(self) -> None:
        """Exceptions from executor.validate() are caught and returned as errors."""

        class FailingValidateExecutor:
            def validate(self, module_id: str, inputs: dict[str, Any]) -> Any:
                raise ModuleNotFoundStubError(module_id)

            async def call_async(self, module_id: str, inputs: dict[str, Any], context: Any = None) -> Any:
                return {"ok": True}

        executor = FailingValidateExecutor()
        router = ExecutionRouter(executor, validate_inputs=True)

        content, is_error = await router.handle_call("nonexistent.module", {})

        assert is_error is True
        assert "nonexistent.module" in content[0]["text"]
