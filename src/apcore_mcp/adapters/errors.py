"""ErrorMapper: apcore error hierarchy → MCP error responses."""

from __future__ import annotations

from typing import Any

from apcore_mcp.constants import ErrorCodes


class ErrorMapper:
    """Maps apcore exceptions to MCP error response dictionaries."""

    # Error codes that should be treated as internal errors
    _INTERNAL_ERROR_CODES = {
        ErrorCodes["CALL_DEPTH_EXCEEDED"],
        ErrorCodes["CIRCULAR_CALL"],
        ErrorCodes["CALL_FREQUENCY_EXCEEDED"],
    }

    # Error codes that require sanitization (hide sensitive details)
    _SANITIZED_ERROR_CODES = {
        ErrorCodes["ACL_DENIED"],
    }

    def to_mcp_error(self, error: Exception) -> dict[str, Any]:
        """
        Convert any exception to an MCP error response dict.

        Returns:
            dict with keys:
                - is_error: True
                - error_type: str (error code or "INTERNAL_ERROR")
                - message: str (safe error message)
                - details: dict | None (optional additional context)
        """
        # Check if it's an apcore ModuleError by checking for expected attributes
        if hasattr(error, "code") and hasattr(error, "message") and hasattr(error, "details"):
            return self._handle_apcore_error(error)

        # Unknown exception - sanitize completely
        return {
            "is_error": True,
            "error_type": ErrorCodes["INTERNAL_ERROR"],
            "message": "Internal error occurred",
            "details": None,
        }

    def _handle_apcore_error(self, error: Exception) -> dict[str, Any]:
        """Handle known apcore errors."""
        code = error.code
        message = error.message
        details = error.details if error.details else None

        # Convert internal errors to generic message
        if code in self._INTERNAL_ERROR_CODES:
            return {
                "is_error": True,
                "error_type": code,
                "message": "Internal error occurred",
                "details": None,
            }

        # Sanitize ACL errors to not leak caller information
        if code in self._SANITIZED_ERROR_CODES:
            return {
                "is_error": True,
                "error_type": code,
                "message": "Access denied",
                "details": None,
            }

        # Schema validation errors need special formatting
        if code == ErrorCodes["SCHEMA_VALIDATION_ERROR"]:
            formatted_message = self._format_validation_errors(details.get("errors", []))
            return {
                "is_error": True,
                "error_type": code,
                "message": formatted_message if formatted_message else message,
                "details": details,
            }

        # All other apcore errors: pass through message and details
        return {
            "is_error": True,
            "error_type": code,
            "message": message,
            "details": details,
        }

    def _format_validation_errors(self, errors: list[dict[str, Any]]) -> str:
        """Format SchemaValidationError field-level errors into readable message."""
        if not errors:
            return "Schema validation failed"

        # Format each error as "field: message"
        error_lines = []
        for err in errors:
            field = err.get("field", "unknown")
            msg = err.get("message", "invalid")
            error_lines.append(f"{field}: {msg}")

        return "Schema validation failed: " + "; ".join(error_lines)

    def _sanitize_message(self, error: Exception) -> str:
        """
        Produce a safe error message that doesn't leak internals.

        For unknown exceptions, returns a generic message.
        """
        return "Internal error occurred"
