"""RegistryListener: dynamic tool registration on registry changes."""

from __future__ import annotations

import logging
import threading
from typing import Any

from mcp import types as mcp_types

from apcore_mcp.constants import REGISTRY_EVENTS
from apcore_mcp.server.factory import MCPServerFactory

logger = logging.getLogger(__name__)


class RegistryListener:
    """Listens for Registry changes and updates MCP tool list."""

    def __init__(
        self,
        registry: Any,
        factory: MCPServerFactory,
    ) -> None:
        """Initialize the listener.

        Args:
            registry: apcore Registry to listen to.
            factory: MCPServerFactory for building Tool objects from new modules.
        """
        self._registry = registry
        self._factory = factory
        self._tools: dict[str, mcp_types.Tool] = {}
        self._lock = threading.Lock()
        self._active = False

    @property
    def tools(self) -> dict[str, mcp_types.Tool]:
        """Return a snapshot of currently registered tools. Thread-safe."""
        with self._lock:
            return dict(self._tools)

    def start(self) -> None:
        """Start listening for Registry events.

        Registers callbacks via registry.on("register", ...) and
        registry.on("unregister", ...).
        Safe to call multiple times (idempotent).
        """
        if self._active:
            return
        self._active = True
        self._registry.on(REGISTRY_EVENTS["REGISTER"], self._on_register)
        self._registry.on(REGISTRY_EVENTS["UNREGISTER"], self._on_unregister)

    def stop(self) -> None:
        """Stop listening for Registry events.

        Sets internal flag that causes callbacks to no-op.
        (apcore Registry does not support callback removal)
        """
        self._active = False

    def _on_register(self, module_id: str, module: Any = None) -> None:
        """Callback for Registry 'register' event.

        Steps:
        1. Check if listener is active (no-op if stopped)
        2. Call registry.get_definition(module_id)
        3. If None (race condition), log warning and return
        4. Call factory.build_tool(descriptor)
        5. Add to internal _tools dict (thread-safe via lock)
        6. Log info: "Tool registered: {module_id}"
        """
        if not self._active:
            return
        descriptor = self._registry.get_definition(module_id)
        if descriptor is None:
            logger.warning("Definition not found for registered module: %s", module_id)
            return
        try:
            tool = self._factory.build_tool(descriptor)
            with self._lock:
                self._tools[module_id] = tool
            logger.info("Tool registered: %s", module_id)
        except Exception as e:
            logger.warning("Failed to build tool for %s: %s", module_id, e)

    def _on_unregister(self, module_id: str, module: Any = None) -> None:
        """Callback for Registry 'unregister' event.

        Steps:
        1. Check if listener is active (no-op if stopped)
        2. Remove module_id from _tools dict (thread-safe)
        3. If module_id not in dict, silently ignore
        4. Log info: "Tool unregistered: {module_id}"
        """
        if not self._active:
            return
        with self._lock:
            removed = self._tools.pop(module_id, None)
        if removed is not None:
            logger.info("Tool unregistered: %s", module_id)
