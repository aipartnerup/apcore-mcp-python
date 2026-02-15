"""Internal type definitions and type aliases for apcore-mcp."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# Type alias: serve() and to_openai_tools() accept either Registry or Executor
RegistryOrExecutor = Any  # Union[Registry, Executor] at runtime
