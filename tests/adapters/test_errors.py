"""Tests for ErrorMapper: apcore errors → MCP error response dicts."""

from __future__ import annotations

from typing import Any

import pytest

from apcore_mcp.adapters.errors import ErrorMapper


# Stub error classes that mimic apcore error hierarchy for testing
# This avoids hard dependency on apcore in unit tests
class ModuleError(Exception):
    """Base error for all apcore framework errors."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
        trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}
        self.cause = cause
        self.trace_id = trace_id


class ModuleNotFoundError(ModuleError):
    """Raised when a module cannot be found."""

    def __init__(self, module_id: str, **kwargs: Any) -> None:
        super().__init__(
            code="MODULE_NOT_FOUND",
            message=f"Module not found: {module_id}",
            details={"module_id": module_id},
            **kwargs,
        )


class SchemaValidationError(ModuleError):
    """Raised when schema validation fails."""

    def __init__(
        self,
        message: str = "Schema validation failed",
        errors: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            code="SCHEMA_VALIDATION_ERROR",
            message=message,
            details={"errors": errors or []},
            **kwargs,
        )


class ACLDeniedError(ModuleError):
    """Raised when ACL denies access."""

    def __init__(self, caller_id: str | None, target_id: str, **kwargs: Any) -> None:
        super().__init__(
            code="ACL_DENIED",
            message=f"Access denied: {caller_id} -> {target_id}",
            details={"caller_id": caller_id, "target_id": target_id},
            **kwargs,
        )


class ModuleTimeoutError(ModuleError):
    """Raised when module execution exceeds timeout."""

    def __init__(self, module_id: str, timeout_ms: int, **kwargs: Any) -> None:
        super().__init__(
            code="MODULE_TIMEOUT",
            message=f"Module {module_id} timed out after {timeout_ms}ms",
            details={"module_id": module_id, "timeout_ms": timeout_ms},
            **kwargs,
        )


class InvalidInputError(ModuleError):
    """Raised for invalid input."""

    def __init__(self, message: str = "Invalid input", **kwargs: Any) -> None:
        super().__init__(code="GENERAL_INVALID_INPUT", message=message, **kwargs)


class CallDepthExceededError(ModuleError):
    """Raised when call chain exceeds maximum depth."""

    def __init__(self, depth: int, max_depth: int, call_chain: list[str], **kwargs: Any) -> None:
        super().__init__(
            code="CALL_DEPTH_EXCEEDED",
            message=f"Call depth {depth} exceeds maximum {max_depth}",
            details={"depth": depth, "max_depth": max_depth, "call_chain": call_chain},
            **kwargs,
        )


class CircularCallError(ModuleError):
    """Raised when a circular call is detected."""

    def __init__(self, module_id: str, call_chain: list[str], **kwargs: Any) -> None:
        super().__init__(
            code="CIRCULAR_CALL",
            message=f"Circular call detected for module {module_id}",
            details={"module_id": module_id, "call_chain": call_chain},
            **kwargs,
        )


class CallFrequencyExceededError(ModuleError):
    """Raised when a module is called too many times."""

    def __init__(
        self,
        module_id: str,
        count: int,
        max_repeat: int,
        call_chain: list[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(
            code="CALL_FREQUENCY_EXCEEDED",
            message=f"Module {module_id} called {count} times, max is {max_repeat}",
            details={
                "module_id": module_id,
                "count": count,
                "max_repeat": max_repeat,
                "call_chain": call_chain,
            },
            **kwargs,
        )


# Test cases
class TestErrorMapper:
    """Test suite for ErrorMapper."""

    @pytest.fixture
    def mapper(self) -> ErrorMapper:
        """Create an ErrorMapper instance."""
        return ErrorMapper()

    def test_module_not_found(self, mapper: ErrorMapper) -> None:
        """ModuleNotFoundError contains module_id in message and error_type."""
        error = ModuleNotFoundError("image.resize")
        result = mapper.to_mcp_error(error)

        assert result["is_error"] is True
        assert result["error_type"] == "MODULE_NOT_FOUND"
        assert "image.resize" in result["message"]

    def test_schema_validation_error(self, mapper: ErrorMapper) -> None:
        """SchemaValidationError includes field details in message."""
        errors = [
            {"field": "name", "message": "required"},
            {"field": "age", "message": "must be positive"},
        ]
        error = SchemaValidationError("Validation failed", errors=errors)
        result = mapper.to_mcp_error(error)

        assert result["is_error"] is True
        assert result["error_type"] == "SCHEMA_VALIDATION_ERROR"
        assert "name" in result["message"]
        assert "age" in result["message"]

    def test_acl_denied(self, mapper: ErrorMapper) -> None:
        """ACLDeniedError says access denied but does NOT leak caller_id."""
        error = ACLDeniedError("user1", "admin.delete")
        result = mapper.to_mcp_error(error)

        assert result["is_error"] is True
        assert result["error_type"] == "ACL_DENIED"
        assert "access denied" in result["message"].lower()
        # Should NOT contain sensitive caller_id
        assert "user1" not in result["message"]

    def test_module_timeout(self, mapper: ErrorMapper) -> None:
        """ModuleTimeoutError mentions timeout."""
        error = ModuleTimeoutError("slow.module", 5000)
        result = mapper.to_mcp_error(error)

        assert result["is_error"] is True
        assert result["error_type"] == "MODULE_TIMEOUT"
        assert "timeout" in result["message"].lower() or "timed out" in result["message"].lower()

    def test_invalid_input(self, mapper: ErrorMapper) -> None:
        """InvalidInputError preserves message."""
        error = InvalidInputError("missing field X")
        result = mapper.to_mcp_error(error)

        assert result["is_error"] is True
        assert result["error_type"] == "GENERAL_INVALID_INPUT"
        assert "missing field X" in result["message"]

    def test_call_depth_exceeded(self, mapper: ErrorMapper) -> None:
        """CallDepthExceededError becomes internal error."""
        error = CallDepthExceededError(10, 10, ["a", "b"])
        result = mapper.to_mcp_error(error)

        assert result["is_error"] is True
        assert result["error_type"] == "CALL_DEPTH_EXCEEDED"
        assert "internal" in result["message"].lower()

    def test_circular_call(self, mapper: ErrorMapper) -> None:
        """CircularCallError becomes internal error."""
        error = CircularCallError("a", ["a", "b", "a"])
        result = mapper.to_mcp_error(error)

        assert result["is_error"] is True
        assert result["error_type"] == "CIRCULAR_CALL"
        assert "internal" in result["message"].lower()

    def test_call_frequency_exceeded(self, mapper: ErrorMapper) -> None:
        """CallFrequencyExceededError becomes internal error."""
        error = CallFrequencyExceededError("a", 5, 3, ["a"])
        result = mapper.to_mcp_error(error)

        assert result["is_error"] is True
        assert result["error_type"] == "CALL_FREQUENCY_EXCEEDED"
        assert "internal" in result["message"].lower()

    def test_unexpected_exception(self, mapper: ErrorMapper) -> None:
        """Unexpected exceptions become generic internal error with NO stack trace."""
        error = ValueError("oops")
        result = mapper.to_mcp_error(error)

        assert result["is_error"] is True
        assert result["error_type"] == "INTERNAL_ERROR"
        assert "internal error" in result["message"].lower()
        # Should NOT leak the original error message
        assert "oops" not in result["message"]

    def test_all_errors_set_is_error(self, mapper: ErrorMapper) -> None:
        """Every error type returns is_error=True."""
        errors = [
            ModuleNotFoundError("test"),
            SchemaValidationError("test"),
            ACLDeniedError("user", "admin"),
            ModuleTimeoutError("test", 100),
            InvalidInputError("test"),
            CallDepthExceededError(1, 1, []),
            CircularCallError("test", []),
            CallFrequencyExceededError("test", 5, 3, []),
            ValueError("unexpected"),
        ]

        for error in errors:
            result = mapper.to_mcp_error(error)
            assert result["is_error"] is True, f"{type(error).__name__} should set is_error=True"

    def test_sanitize_no_stack_trace(self, mapper: ErrorMapper) -> None:
        """Unexpected exceptions don't leak traceback info."""
        error = RuntimeError("internal details that should not be exposed")
        result = mapper.to_mcp_error(error)

        # Should not contain any of the internal error details
        assert "internal details" not in result["message"]
        assert "RuntimeError" not in result["message"]
        # Should be generic message
        assert result["message"] == "Internal error occurred"
