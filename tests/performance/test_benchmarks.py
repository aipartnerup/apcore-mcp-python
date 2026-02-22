"""Performance benchmark tests for apcore-mcp.

TC-PERF-001 through TC-PERF-006: schema conversion speed, routing overhead,
memory consumption, concurrency correctness, large schema handling, and
OpenAI conversion throughput.
"""

from __future__ import annotations

import asyncio
import json
import time
import tracemalloc
from typing import Any

from apcore_mcp.adapters.schema import SchemaConverter
from apcore_mcp.converters.openai import OpenAIConverter
from apcore_mcp.server.factory import MCPServerFactory
from apcore_mcp.server.router import ExecutionRouter
from tests.conftest import ModuleAnnotations, ModuleDescriptor

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal registry stub for performance tests."""

    def __init__(self, descriptors: list[ModuleDescriptor] | None = None) -> None:
        self._descriptors: dict[str, ModuleDescriptor] = {d.module_id: d for d in (descriptors or [])}

    def list(self, tags: list[str] | None = None, prefix: str | None = None) -> list[str]:
        return sorted(self._descriptors.keys())

    def get_definition(self, module_id: str) -> ModuleDescriptor | None:
        return self._descriptors.get(module_id)


class StubExecutor:
    """Stub executor with configurable delay and per-module results."""

    def __init__(
        self,
        results: dict[str, Any] | None = None,
        errors: dict[str, Exception] | None = None,
        delay: float = 0,
    ) -> None:
        self._results = results or {}
        self._errors = errors or {}
        self._delay = delay

    async def call_async(self, module_id: str, inputs: dict[str, Any] | None = None) -> Any:
        if self._delay:
            await asyncio.sleep(self._delay)
        if module_id in self._errors:
            raise self._errors[module_id]
        return self._results.get(module_id, {"ok": True})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(index: int, num_properties: int, with_ref: bool) -> ModuleDescriptor:
    """Create a ModuleDescriptor with the given number of properties.

    When *with_ref* is True, the schema includes a ``$defs`` section and
    one of the properties references it via ``$ref``.
    """
    properties: dict[str, Any] = {}
    for p in range(num_properties):
        properties[f"field_{p}"] = {
            "type": "string",
            "description": f"Field {p} for module {index}",
        }

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": ["field_0"],
    }

    if with_ref:
        schema["$defs"] = {
            "SubItem": {
                "type": "object",
                "properties": {
                    "sub_name": {"type": "string"},
                    "sub_value": {"type": "integer"},
                },
                "required": ["sub_name"],
            }
        }
        schema["properties"]["ref_field"] = {"$ref": "#/$defs/SubItem"}

    return ModuleDescriptor(
        module_id=f"perf.module_{index:04d}",
        description=f"Performance test module {index}",
        input_schema=schema,
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        annotations=ModuleAnnotations(idempotent=True),
    )


def _make_descriptors(count: int = 100) -> list[ModuleDescriptor]:
    """Create *count* descriptors, ~20% with $ref nodes."""
    descriptors = []
    for i in range(count):
        num_props = 5 + (i % 6)  # 5-10 properties
        with_ref = i % 5 == 0  # 20% have $ref
        descriptors.append(_make_descriptor(i, num_props, with_ref))
    return descriptors


# ---------------------------------------------------------------------------
# TC-PERF-001: Schema conversion for 100 modules under 100ms
# ---------------------------------------------------------------------------


class TestSchemaConversionPerformance:
    """TC-PERF-001: build_tools for 100 modules must complete within 100ms."""

    def test_build_tools_100_modules_under_100ms(self) -> None:
        """Schema conversion for 100 modules with 5-10 properties (20% $ref) < 100ms."""
        descriptors = _make_descriptors(100)
        registry = StubRegistry(descriptors)
        factory = MCPServerFactory()

        start = time.perf_counter()
        tools = factory.build_tools(registry)
        elapsed = time.perf_counter() - start

        assert len(tools) == 100, f"Expected 100 tools, got {len(tools)}"
        assert elapsed < 0.1, f"build_tools took {elapsed * 1000:.1f}ms, expected < 100ms"


# ---------------------------------------------------------------------------
# TC-PERF-002: Tool call routing overhead under 5ms
# ---------------------------------------------------------------------------


class TestRoutingOverhead:
    """TC-PERF-002: handle_call routing overhead must average under 5ms."""

    async def test_routing_overhead_under_5ms(self) -> None:
        """1000 handle_call invocations with instant executor average < 5ms each."""
        executor = StubExecutor(results={"perf.test": {"ok": True}}, delay=0)
        router = ExecutionRouter(executor)

        iterations = 1000
        start = time.perf_counter()
        for _ in range(iterations):
            content, is_error = await router.handle_call("perf.test", {"key": "value"})
            assert is_error is False
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 5, f"Average routing overhead is {avg_ms:.2f}ms, expected < 5ms"


# ---------------------------------------------------------------------------
# TC-PERF-003: Memory overhead under 10MB for 100 modules
# ---------------------------------------------------------------------------


class TestMemoryOverhead:
    """TC-PERF-003: building tools for 100 modules must use < 10MB additional memory."""

    def test_memory_overhead_under_10mb(self) -> None:
        """Memory increase after build_tools for 100 modules < 10MB."""
        descriptors = _make_descriptors(100)
        registry = StubRegistry(descriptors)
        factory = MCPServerFactory()

        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        tools = factory.build_tools(registry)

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # Calculate size difference
        stats_before = snapshot_before.statistics("filename")
        stats_after = snapshot_after.statistics("filename")
        total_before = sum(s.size for s in stats_before)
        total_after = sum(s.size for s in stats_after)
        delta_bytes = total_after - total_before
        delta_mb = delta_bytes / (1024 * 1024)

        assert len(tools) == 100
        assert delta_mb < 10, f"Memory increase was {delta_mb:.2f}MB, expected < 10MB"


# ---------------------------------------------------------------------------
# TC-PERF-004: 10 concurrent tool calls handled correctly
# ---------------------------------------------------------------------------


class TestConcurrentCalls:
    """TC-PERF-004: 10 concurrent handle_call invocations run in parallel correctly."""

    async def test_10_concurrent_calls_within_500ms(self) -> None:
        """10 concurrent calls with 10ms delay each complete < 500ms total."""
        # Each call gets a unique result to verify no cross-contamination
        results = {f"module.{i}": {"id": i, "data": f"result_{i}"} for i in range(10)}
        executor = StubExecutor(results=results, delay=0.01)
        router = ExecutionRouter(executor)

        start = time.perf_counter()
        tasks = [router.handle_call(f"module.{i}", {"index": i}) for i in range(10)]
        outcomes = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

        # All must complete within 500ms (parallel, not sequential 100ms)
        assert elapsed < 0.5, f"10 concurrent calls took {elapsed * 1000:.1f}ms, expected < 500ms"

        # All results must be successful
        for _content, is_error in outcomes:
            assert is_error is False, "Expected no error for any concurrent call"

        # Verify no cross-contamination: each result matches its module
        for i, (content, _) in enumerate(outcomes):
            parsed = json.loads(content[0]["text"])
            assert parsed["id"] == i, f"Result cross-contamination: expected id={i}, got id={parsed['id']}"
            assert (
                parsed["data"] == f"result_{i}"
            ), f"Result cross-contamination: expected data='result_{i}', got '{parsed['data']}'"


# ---------------------------------------------------------------------------
# TC-PERF-005: Large schema with 50+ properties converts correctly
# ---------------------------------------------------------------------------


class TestLargeSchemaConversion:
    """TC-PERF-005: schema with 50+ properties, nested objects, $ref converts < 50ms."""

    def test_large_schema_50_properties_under_50ms(self) -> None:
        """Large schema with 50 properties, nested objects, and $ref nodes converts < 50ms."""
        # Build a schema with 50 properties, nested objects, and $ref nodes
        properties: dict[str, Any] = {}
        for i in range(50):
            if i % 10 == 0:
                # Nested object every 10th property
                properties[f"nested_{i}"] = {
                    "type": "object",
                    "properties": {
                        "inner_a": {"type": "string"},
                        "inner_b": {"type": "integer"},
                        "inner_c": {
                            "type": "object",
                            "properties": {
                                "deep": {"type": "boolean"},
                            },
                        },
                    },
                }
            elif i % 5 == 0:
                # $ref every 5th property (but not 10th)
                properties[f"ref_field_{i}"] = {"$ref": "#/$defs/SharedConfig"}
            else:
                properties[f"field_{i}"] = {
                    "type": "string",
                    "description": f"Property {i}",
                }

        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "SharedConfig": {
                    "type": "object",
                    "properties": {
                        "config_name": {"type": "string"},
                        "config_value": {"type": "number"},
                        "enabled": {"type": "boolean"},
                    },
                    "required": ["config_name"],
                }
            },
            "properties": properties,
            "required": ["field_1", "field_2"],
        }

        descriptor = ModuleDescriptor(
            module_id="perf.large_schema",
            description="Module with 50+ properties",
            input_schema=schema,
            output_schema={"type": "object"},
            annotations=ModuleAnnotations(),
        )

        converter = SchemaConverter()

        start = time.perf_counter()
        result = converter.convert_input_schema(descriptor)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.05, f"Large schema conversion took {elapsed * 1000:.1f}ms, expected < 50ms"

        # Assert correct property count
        assert len(result["properties"]) == 50, f"Expected 50 properties, got {len(result['properties'])}"

        # Assert no $defs remain
        assert "$defs" not in result, "$defs should be removed after conversion"
        # Assert no $ref remains anywhere in the output
        result_str = json.dumps(result)
        assert "$ref" not in result_str, "$ref should be fully inlined"


# ---------------------------------------------------------------------------
# TC-PERF-006: to_openai_tools for 100 modules under 200ms
# ---------------------------------------------------------------------------


class TestOpenAIConversionPerformance:
    """TC-PERF-006: OpenAI conversion for 100 modules must complete within 200ms."""

    def test_openai_conversion_100_modules_under_200ms(self) -> None:
        """convert_registry for 100 modules with varied schemas < 200ms."""
        descriptors = _make_descriptors(100)
        registry = StubRegistry(descriptors)
        converter = OpenAIConverter()

        start = time.perf_counter()
        tools = converter.convert_registry(registry)
        elapsed = time.perf_counter() - start

        assert len(tools) == 100, f"Expected 100 tools, got {len(tools)}"
        assert elapsed < 0.2, f"OpenAI conversion took {elapsed * 1000:.1f}ms, expected < 200ms"

        # Verify each tool has the expected structure
        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]
