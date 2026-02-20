"""Internal utility functions for apcore-mcp."""

from __future__ import annotations

from typing import Any


def resolve_registry(registry_or_executor: Any) -> Any:
    """Extract Registry from either a Registry or Executor instance."""
    if hasattr(registry_or_executor, "registry"):
        # It's an Executor — get its registry
        return registry_or_executor.registry
    # Assume it's a Registry
    return registry_or_executor


def resolve_executor(registry_or_executor: Any) -> Any:
    """Get or create an Executor from either a Registry or Executor instance."""
    if hasattr(registry_or_executor, "call_async"):
        # Already an Executor
        return registry_or_executor
    # It's a Registry — create a default Executor
    from apcore.executor import Executor

    return Executor(registry_or_executor)
