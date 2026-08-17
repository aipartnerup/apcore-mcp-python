"""Cross-language conformance: apcore Module -> MCP Tool.

Drives ``MCPServerFactory.build_tool`` from the shared fixture at
``apcore-mcp/conformance/fixtures/tool_mapping.json``. The TypeScript and Rust
bridges run the same fixture through their own factories; all three must agree
on the tool name, input schema and annotation hints.

The fixture pins SRS section 7.1: the MCP tool name keeps the module id's dot
notation. Hyphenation, ``x-llm-description`` promotion and ``x-`` stripping are
the OpenAI converter's job and are covered by
``test_openai_tool_mapping_conformance.py``.
"""

from __future__ import annotations

import pytest
from apcore import ModuleAnnotations, ModuleDescriptor
from apcore_mcp.server.factory import MCPServerFactory

from tests.conformance_fixtures import load_fixture

_FIXTURE = load_fixture("tool_mapping.json")


def _descriptor(module: dict) -> ModuleDescriptor:
    annotations = module.get("annotations")
    return ModuleDescriptor(
        module_id=module["module_id"],
        name=None,
        description=module.get("description", ""),
        documentation=None,
        input_schema=module.get("input_schema", {}),
        output_schema=module.get("output_schema", {}),
        version="1.0.0",
        annotations=ModuleAnnotations.from_dict(annotations) if annotations else None,
    )


@pytest.mark.parametrize("case", _FIXTURE["test_cases"], ids=lambda c: c["id"])
def test_conformance_module_to_mcp_tool(case: dict):
    tool = MCPServerFactory().build_tool(_descriptor(case["input_module"]))
    expected = case["expected_mcp_tool"]

    assert tool.name == expected["name"], f"{case['id']}: tool name mismatch"
    assert tool.description == expected["description"], f"{case['id']}: description mismatch"
    assert tool.inputSchema == expected["inputSchema"], f"{case['id']}: inputSchema mismatch"

    got_annotations = tool.annotations.model_dump(exclude_none=True) if tool.annotations else {}
    for key, value in expected["annotations"].items():
        assert got_annotations.get(key) == value, (
            f"{case['id']}: annotation {key} — got {got_annotations.get(key)!r}, expected {value!r}"
        )
