"""Security tests for apcore-mcp.

TC-SEC-001 through TC-SEC-006: ACL leak prevention, stack trace sanitization,
malformed input handling, oversized input handling, call chain info hiding,
and default host binding.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

import apcore_mcp
from apcore_mcp.adapters.errors import ErrorMapper
from apcore_mcp.server.router import ExecutionRouter
from apcore_mcp.server.transport import TransportManager

# ---------------------------------------------------------------------------
# Stub error classes (same pattern as tests/server/test_router.py)
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
# Stub executor
# ---------------------------------------------------------------------------


class StubExecutor:
    """Stub executor that raises a configured error or returns a result."""

    def __init__(
        self,
        results: dict[str, Any] | None = None,
        errors: dict[str, Exception] | None = None,
        default_error: Exception | None = None,
    ) -> None:
        self._results = results or {}
        self._errors = errors or {}
        self._default_error = default_error

    async def call_async(self, module_id: str, inputs: dict[str, Any] | None = None) -> Any:
        if module_id in self._errors:
            raise self._errors[module_id]
        if self._default_error:
            raise self._default_error
        return self._results.get(module_id, {"ok": True})


# ---------------------------------------------------------------------------
# TC-SEC-001: ACL denied calls do not leak caller identity
# ---------------------------------------------------------------------------


class TestACLDeniedNoLeak:
    """TC-SEC-001: ACL denied responses must not expose caller identity."""

    async def test_acl_denied_does_not_leak_caller_id(self) -> None:
        """Response to ACL denied must not contain caller_id and must say 'Access denied'."""
        error = ACLDeniedStubError(
            caller_id="admin_user_42",
            target_id="secret.module",
        )
        executor = StubExecutor(
            errors={"secret.module": error},
        )
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("secret.module", {})

        assert is_error is True
        response_text = content[0]["text"]
        assert "admin_user_42" not in response_text, "Response must not contain caller identity"
        assert response_text == "Access denied", f"Expected exactly 'Access denied', got '{response_text}'"


# ---------------------------------------------------------------------------
# TC-SEC-002: Unexpected exceptions do not leak stack traces
# ---------------------------------------------------------------------------


class TestNoStackTraceLeak:
    """TC-SEC-002: unexpected exceptions must not expose sensitive details."""

    @pytest.mark.parametrize(
        "exception,forbidden_substrings",
        [
            (
                RuntimeError("Connection refused to postgres://admin:secret@db:5432/prod"),
                ["postgres", "secret"],
            ),
            (
                FileNotFoundError("/etc/shadow"),
                ["/etc/shadow"],
            ),
            (
                PermissionError("Cannot access /root/.ssh/id_rsa"),
                ["/root/.ssh"],
            ),
            (
                ValueError("Invalid token: eyJhbGciOiJIUzI1NiJ9.eyJ0ZXN0IjoiZGF0YSJ9"),
                ["eyJhbG"],
            ),
        ],
        ids=[
            "postgres_connection_string",
            "shadow_file_path",
            "ssh_private_key_path",
            "jwt_token",
        ],
    )
    async def test_sensitive_exception_sanitized(
        self,
        exception: Exception,
        forbidden_substrings: list[str],
    ) -> None:
        """Unexpected exceptions must be mapped to 'Internal error occurred'."""
        executor = StubExecutor(default_error=exception)
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("any.module", {})

        assert is_error is True
        response_text = content[0]["text"]
        assert response_text == "Internal error occurred", f"Expected 'Internal error occurred', got '{response_text}'"
        for substring in forbidden_substrings:
            assert substring not in response_text, f"Response must not contain '{substring}'"


# ---------------------------------------------------------------------------
# TC-SEC-003: Malformed input handled safely
# ---------------------------------------------------------------------------


class TestMalformedInput:
    """TC-SEC-003: malformed/malicious inputs must not cause unhandled exceptions."""

    @pytest.mark.parametrize(
        "malicious_input",
        [
            # XSS payload
            {"field": "<script>alert('xss')</script>"},
            # SQL injection
            {"field": "'; DROP TABLE users; --"},
            # Template injection
            {"field": "{{7*7}}"},
            # Null bytes
            {"field": "hello\x00world"},
            # Unicode edge cases
            {"field": "\ud800"},
            # Deeply nested dict
            {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}},
            # Array with mixed types
            {"items": [1, "two", None, True, {"nested": "obj"}]},
            # Empty string key
            {"": "empty_key"},
            # Very long key name
            {"k" * 10000: "long_key"},
        ],
        ids=[
            "xss_payload",
            "sql_injection",
            "template_injection",
            "null_bytes",
            "unicode_edge_case",
            "deeply_nested",
            "mixed_array",
            "empty_key",
            "long_key_name",
        ],
    )
    async def test_malformed_input_handled_safely(self, malicious_input: dict[str, Any]) -> None:
        """Malicious inputs produce either success or error, never unhandled exception."""
        executor = StubExecutor(results={"test.module": {"ok": True}})
        router = ExecutionRouter(executor)

        # Must not raise -- either success or graceful error
        content, is_error = await router.handle_call("test.module", malicious_input)

        assert isinstance(content, list), "content must be a list"
        assert len(content) >= 1, "content must have at least one element"
        assert isinstance(is_error, bool), "is_error must be a boolean"
        assert content[0]["type"] == "text", "content type must be 'text'"


# ---------------------------------------------------------------------------
# TC-SEC-004: Oversized input handled gracefully
# ---------------------------------------------------------------------------


class TestOversizedInput:
    """TC-SEC-004: very large inputs must not cause memory exhaustion crashes."""

    async def test_oversized_10mb_string_handled(self) -> None:
        """A 10MB string value in arguments does not crash the router."""
        large_value = "A" * (10 * 1024 * 1024)  # 10MB
        arguments = {"data": large_value}

        executor = StubExecutor(results={"test.module": {"ok": True}})
        router = ExecutionRouter(executor)

        # Must not crash -- either success or error is acceptable
        content, is_error = await router.handle_call("test.module", arguments)

        assert isinstance(content, list), "content must be a list"
        assert len(content) >= 1, "content must have at least one element"
        assert isinstance(is_error, bool), "is_error must be a boolean"

    async def test_oversized_many_keys_handled(self) -> None:
        """Arguments with 10,000 keys do not crash the router."""
        arguments = {f"key_{i}": f"value_{i}" for i in range(10_000)}

        executor = StubExecutor(results={"test.module": {"ok": True}})
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("test.module", arguments)

        assert isinstance(content, list)
        assert isinstance(is_error, bool)


# ---------------------------------------------------------------------------
# TC-SEC-005: Error mapper never exposes call chain details
# ---------------------------------------------------------------------------


class TestCallChainNotExposed:
    """TC-SEC-005: error mapper must never expose call chain details."""

    @pytest.mark.parametrize(
        "error,forbidden_substrings",
        [
            (
                CallDepthExceededStubError(
                    depth=10,
                    max_depth=5,
                    call_chain=["module.a", "module.b", "module.c"],
                ),
                ["module.a", "module.b", "module.c"],
            ),
            (
                CircularCallStubError(
                    module_id="module.x",
                    call_chain=["module.x", "module.y", "module.x"],
                ),
                ["module.x", "module.y"],
            ),
            (
                CallFrequencyExceededStubError(
                    module_id="spam",
                    count=100,
                    max_repeat=10,
                    call_chain=["spam", "helper.a"],
                ),
                ["spam", "helper.a"],
            ),
        ],
        ids=[
            "call_depth_exceeded",
            "circular_call",
            "call_frequency_exceeded",
        ],
    )
    async def test_call_chain_not_in_response(
        self,
        error: Exception,
        forbidden_substrings: list[str],
    ) -> None:
        """Call chain module names must not appear in the error response."""
        executor = StubExecutor(default_error=error)
        router = ExecutionRouter(executor)

        content, is_error = await router.handle_call("any.module", {})

        assert is_error is True
        response_text = content[0]["text"]
        assert response_text == "Internal error occurred", f"Expected 'Internal error occurred', got '{response_text}'"
        for substring in forbidden_substrings:
            assert substring not in response_text, f"Response must not contain call chain module '{substring}'"

    def test_error_mapper_directly_hides_call_chain(self) -> None:
        """ErrorMapper.to_mcp_error strips call chain from all internal error types."""
        mapper = ErrorMapper()

        errors = [
            CallDepthExceededStubError(10, 5, ["module.a", "module.b"]),
            CircularCallStubError("module.x", ["module.x", "module.y"]),
            CallFrequencyExceededStubError("spam", 100, 10, ["spam", "helper.a"]),
        ]

        for error in errors:
            result = mapper.to_mcp_error(error)
            assert (
                result["message"] == "Internal error occurred"
            ), f"ErrorMapper must return 'Internal error occurred' for {type(error).__name__}"
            assert result["details"] is None, f"ErrorMapper must not expose details for {type(error).__name__}"


# ---------------------------------------------------------------------------
# TC-SEC-006: Default HTTP host is localhost only
# ---------------------------------------------------------------------------


class TestDefaultHostLocalhost:
    """TC-SEC-006: all default HTTP host parameters must be 127.0.0.1."""

    def test_serve_default_host_is_localhost(self) -> None:
        """serve() function default host parameter is 127.0.0.1."""
        sig = inspect.signature(apcore_mcp.serve)
        host_param = sig.parameters["host"]
        assert (
            host_param.default == "127.0.0.1"
        ), f"serve() default host is '{host_param.default}', expected '127.0.0.1'"

    def test_transport_streamable_http_default_host_is_localhost(self) -> None:
        """TransportManager.run_streamable_http default host is 127.0.0.1."""
        sig = inspect.signature(TransportManager.run_streamable_http)
        host_param = sig.parameters["host"]
        assert (
            host_param.default == "127.0.0.1"
        ), f"run_streamable_http default host is '{host_param.default}', expected '127.0.0.1'"

    def test_transport_sse_default_host_is_localhost(self) -> None:
        """TransportManager.run_sse default host is 127.0.0.1."""
        sig = inspect.signature(TransportManager.run_sse)
        host_param = sig.parameters["host"]
        assert (
            host_param.default == "127.0.0.1"
        ), f"run_sse default host is '{host_param.default}', expected '127.0.0.1'"
