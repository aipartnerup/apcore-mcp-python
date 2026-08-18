"""Cross-language conformance: apcore Module -> OpenAI function definition.

Drives ``OpenAIConverter.convert_descriptor`` from the shared fixture at
``apcore-mcp/conformance/fixtures/openai_tool_mapping.json``. Assertions are
field-level rather than whole-object: the three bridges are known to join
annotation sections into the description differently, and pinning that
byte-for-byte would assert a formatting accident rather than the mapping rule.
"""

from __future__ import annotations

import pytest
from apcore import ModuleAnnotations, ModuleDescriptor

from apcore_mcp.converters.openai import OpenAIConverter
from tests.conformance_fixtures import load_fixture

_FIXTURE = load_fixture("openai_tool_mapping.json")


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
def test_conformance_module_to_openai_function(case: dict):
    options = case.get("options", {})
    result = OpenAIConverter().convert_descriptor(
        _descriptor(case["input_module"]),
        embed_annotations=options.get("embed_annotations", False),
        strict=options.get("strict", True),
    )
    function = result["function"]

    assert function["name"] == case["expected_function_name"], f"{case['id']}: function name mismatch"

    properties = function["parameters"].get("properties", {})

    if "expected_property_description" in case:
        spec = case["expected_property_description"]
        got = properties.get(spec["property"], {}).get("description")
        assert (
            got == spec["value"]
        ), f"{case['id']}: {spec['property']}.description — got {got!r}, expected {spec['value']!r}"

    if "expected_absent_property_keys" in case:
        target = case.get("expected_property_of")
        scoped = {target: properties.get(target, {})} if target else properties
        for prop_name, prop_schema in scoped.items():
            for forbidden in case["expected_absent_property_keys"]:
                assert forbidden not in prop_schema, f"{case['id']}: property {prop_name} still carries {forbidden!r}"

    for needle in case.get("expected_description_contains", []):
        assert (
            needle in function["description"]
        ), f"{case['id']}: description missing {needle!r} — got {function['description']!r}"
    for needle in case.get("expected_description_not_contains", []):
        assert (
            needle not in function["description"]
        ), f"{case['id']}: description leaked {needle!r} — got {function['description']!r}"
