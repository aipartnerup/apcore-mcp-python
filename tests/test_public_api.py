"""Top-level public-API surface tests.

[D1-001] AsyncTaskBridge, META_TOOL_NAMES, and APCORE_META_TOOL_PREFIX must
be importable from ``apcore_mcp`` directly so the Python public API mirrors
TypeScript's ``src/index.ts:88`` re-export block:

    export { AsyncTaskBridge, createAsyncTaskBridge, META_TOOL_NAMES,
             APCORE_META_TOOL_PREFIX } from "./server/async-task-bridge.js";

(``createAsyncTaskBridge`` is a TS factory helper that has no Python
counterpart — the Python class ``AsyncTaskBridge`` is instantiated
directly.)
"""

from __future__ import annotations

import apcore_mcp


class TestAsyncTaskBridgeReExports:
    def test_async_task_bridge_importable_from_top_level(self) -> None:
        from apcore_mcp import AsyncTaskBridge
        from apcore_mcp.server.async_task_bridge import AsyncTaskBridge as Internal

        assert AsyncTaskBridge is Internal

    def test_meta_tool_names_importable_from_top_level(self) -> None:
        from apcore_mcp import META_TOOL_NAMES
        from apcore_mcp.server.async_task_bridge import META_TOOL_NAMES as Internal

        assert META_TOOL_NAMES is Internal
        # Sanity: the tuple mirrors the TS list.
        assert "__apcore_task_submit" in META_TOOL_NAMES
        assert "__apcore_module_preview" in META_TOOL_NAMES

    def test_apcore_meta_tool_prefix_importable_from_top_level(self) -> None:
        from apcore_mcp import APCORE_META_TOOL_PREFIX
        from apcore_mcp.server.async_task_bridge import RESERVED_PREFIX

        # The TS name is APCORE_META_TOOL_PREFIX; Python's internal symbol is
        # RESERVED_PREFIX. The top-level alias must match the TS name.
        assert APCORE_META_TOOL_PREFIX == RESERVED_PREFIX
        assert APCORE_META_TOOL_PREFIX == "__apcore_"


class TestPublicApiAllList:
    def test_new_re_exports_listed_in_all(self) -> None:
        assert "AsyncTaskBridge" in apcore_mcp.__all__
        assert "META_TOOL_NAMES" in apcore_mcp.__all__
        assert "APCORE_META_TOOL_PREFIX" in apcore_mcp.__all__
