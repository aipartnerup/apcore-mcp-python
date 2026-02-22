"""End-to-end tests for apcore-mcp.

These tests validate the full system behavior from the perspective of an
external consumer, using real components throughout the stack. Only the
Executor and Registry are stubbed since they represent the apcore boundary.

Tests that require real subprocess/network (TC-E2E-001, TC-E2E-002,
TC-E2E-003) are skipped because they need real apcore modules.
"""

from __future__ import annotations

import pytest
from apcore_mcp import to_openai_tools
from apcore_mcp.server.factory import MCPServerFactory
from mcp import types as mcp_types

from tests.conftest import ModuleAnnotations, ModuleDescriptor

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubRegistry:
    """Stub for apcore Registry."""

    def __init__(self, descriptors: list[ModuleDescriptor] | None = None) -> None:
        self._descriptors: dict[str, ModuleDescriptor] = {d.module_id: d for d in (descriptors or [])}

    def list(self, tags: list[str] | None = None, prefix: str | None = None) -> list[str]:
        ids = list(self._descriptors.keys())
        if prefix is not None:
            ids = [mid for mid in ids if mid.startswith(prefix)]
        if tags is not None:
            tag_set = set(tags)
            ids = [mid for mid in ids if tag_set.issubset(set(self._descriptors[mid].tags))]
        return sorted(ids)

    def get_definition(self, module_id: str) -> ModuleDescriptor | None:
        return self._descriptors.get(module_id)


# ---------------------------------------------------------------------------
# TC-E2E-004: Multi-module registry with mixed annotations
# ---------------------------------------------------------------------------


class TestMultiModuleMixedAnnotations:
    """TC-E2E-004: Build MCP tools from a multi-module registry with varied annotations.

    Three modules with different annotation profiles:
    - reader.get: readonly=True, idempotent=True
    - writer.delete: destructive=True, requires_approval=True
    - worker.process: annotations=None (defaults)

    Validates that the full pipeline (MCPServerFactory with real SchemaConverter
    and AnnotationMapper) produces correct MCP ToolAnnotations for each module.
    """

    @pytest.fixture
    def reader_desc(self) -> ModuleDescriptor:
        return ModuleDescriptor(
            module_id="reader.get",
            description="Read data from a source",
            input_schema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Data source identifier"},
                    "limit": {"type": "integer", "description": "Max items to return"},
                },
                "required": ["source"],
            },
            output_schema={
                "type": "object",
                "properties": {"items": {"type": "array", "items": {"type": "object"}}},
            },
            annotations=ModuleAnnotations(readonly=True, idempotent=True),
        )

    @pytest.fixture
    def writer_desc(self) -> ModuleDescriptor:
        return ModuleDescriptor(
            module_id="writer.delete",
            description="Delete records from the database",
            input_schema={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "description": "ID of the record"},
                    "force": {"type": "boolean", "description": "Force delete"},
                },
                "required": ["record_id"],
            },
            output_schema={
                "type": "object",
                "properties": {"deleted": {"type": "boolean"}},
            },
            annotations=ModuleAnnotations(destructive=True, requires_approval=True, open_world=False),
        )

    @pytest.fixture
    def worker_desc(self) -> ModuleDescriptor:
        return ModuleDescriptor(
            module_id="worker.process",
            description="Process a batch of items",
            input_schema={
                "type": "object",
                "properties": {
                    "batch_id": {"type": "string"},
                    "concurrency": {"type": "integer"},
                },
                "required": ["batch_id"],
            },
            output_schema={
                "type": "object",
                "properties": {"processed": {"type": "integer"}},
            },
            annotations=None,
        )

    @pytest.fixture
    def registry(
        self,
        reader_desc: ModuleDescriptor,
        writer_desc: ModuleDescriptor,
        worker_desc: ModuleDescriptor,
    ) -> StubRegistry:
        return StubRegistry([reader_desc, writer_desc, worker_desc])

    @pytest.fixture
    def tools(self, registry: StubRegistry) -> list[mcp_types.Tool]:
        factory = MCPServerFactory()
        return factory.build_tools(registry)

    @pytest.fixture
    def tool_by_name(self, tools: list[mcp_types.Tool]) -> dict[str, mcp_types.Tool]:
        return {t.name: t for t in tools}

    def test_three_tools_built(self, tools: list[mcp_types.Tool]) -> None:
        """All three modules produce MCP Tools."""
        assert len(tools) == 3

    def test_tool_names(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """Tool names match module IDs."""
        assert set(tool_by_name.keys()) == {"reader.get", "writer.delete", "worker.process"}

    # -- reader.get annotations --

    def test_reader_readonly_hint(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """reader.get has readOnlyHint=True."""
        tool = tool_by_name["reader.get"]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True

    def test_reader_idempotent_hint(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """reader.get has idempotentHint=True."""
        tool = tool_by_name["reader.get"]
        assert tool.annotations is not None
        assert tool.annotations.idempotentHint is True

    def test_reader_destructive_hint_false(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """reader.get has destructiveHint=False (default)."""
        tool = tool_by_name["reader.get"]
        assert tool.annotations is not None
        assert tool.annotations.destructiveHint is False

    def test_reader_open_world_hint_default(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """reader.get has openWorldHint=True (default)."""
        tool = tool_by_name["reader.get"]
        assert tool.annotations is not None
        assert tool.annotations.openWorldHint is True

    # -- writer.delete annotations --

    def test_writer_destructive_hint(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """writer.delete has destructiveHint=True."""
        tool = tool_by_name["writer.delete"]
        assert tool.annotations is not None
        assert tool.annotations.destructiveHint is True

    def test_writer_open_world_hint_false(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """writer.delete has openWorldHint=False."""
        tool = tool_by_name["writer.delete"]
        assert tool.annotations is not None
        assert tool.annotations.openWorldHint is False

    def test_writer_readonly_hint_false(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """writer.delete has readOnlyHint=False (default)."""
        tool = tool_by_name["writer.delete"]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False

    def test_writer_idempotent_hint_false(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """writer.delete has idempotentHint=False (default)."""
        tool = tool_by_name["writer.delete"]
        assert tool.annotations is not None
        assert tool.annotations.idempotentHint is False

    # -- worker.process annotations (None -> defaults) --

    def test_worker_default_readonly_hint(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """worker.process (annotations=None) has readOnlyHint=False."""
        tool = tool_by_name["worker.process"]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False

    def test_worker_default_destructive_hint(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """worker.process (annotations=None) has destructiveHint=False."""
        tool = tool_by_name["worker.process"]
        assert tool.annotations is not None
        assert tool.annotations.destructiveHint is False

    def test_worker_default_idempotent_hint(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """worker.process (annotations=None) has idempotentHint=False."""
        tool = tool_by_name["worker.process"]
        assert tool.annotations is not None
        assert tool.annotations.idempotentHint is False

    def test_worker_default_open_world_hint(self, tool_by_name: dict[str, mcp_types.Tool]) -> None:
        """worker.process (annotations=None) has openWorldHint=True."""
        tool = tool_by_name["worker.process"]
        assert tool.annotations is not None
        assert tool.annotations.openWorldHint is True

    # -- Schema validation for all tools --

    def test_all_tools_have_valid_input_schema(self, tools: list[mcp_types.Tool]) -> None:
        """All tools have inputSchema with type: 'object'."""
        for tool in tools:
            assert tool.inputSchema["type"] == "object"
            assert "properties" in tool.inputSchema

    def test_all_tools_have_descriptions(self, tools: list[mcp_types.Tool]) -> None:
        """All tools have non-empty descriptions."""
        for tool in tools:
            assert tool.description is not None
            assert len(tool.description) > 0


# ---------------------------------------------------------------------------
# TC-E2E-008: Verify server wires with zero modules
# ---------------------------------------------------------------------------


class TestZeroModules:
    """TC-E2E-008: Server components work correctly with an empty registry.

    Validates that both to_openai_tools() and MCPServerFactory.build_tools()
    gracefully handle a registry with no modules.
    """

    @pytest.fixture
    def empty_registry(self) -> StubRegistry:
        return StubRegistry([])

    def test_openai_tools_returns_empty_list(self, empty_registry: StubRegistry) -> None:
        """to_openai_tools() returns an empty list for an empty registry."""
        tools = to_openai_tools(empty_registry)
        assert isinstance(tools, list)
        assert tools == []

    def test_build_tools_returns_empty_list(self, empty_registry: StubRegistry) -> None:
        """MCPServerFactory.build_tools() returns an empty list for an empty registry."""
        factory = MCPServerFactory()
        tools = factory.build_tools(empty_registry)
        assert isinstance(tools, list)
        assert tools == []

    def test_openai_tools_return_type(self, empty_registry: StubRegistry) -> None:
        """to_openai_tools() always returns a list, not None."""
        result = to_openai_tools(empty_registry)
        assert result is not None
        assert isinstance(result, list)

    def test_build_tools_return_type(self, empty_registry: StubRegistry) -> None:
        """MCPServerFactory.build_tools() always returns a list, not None."""
        factory = MCPServerFactory()
        result = factory.build_tools(empty_registry)
        assert result is not None
        assert isinstance(result, list)
