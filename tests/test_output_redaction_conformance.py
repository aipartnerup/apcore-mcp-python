"""Cross-language conformance: F-038 tool output redaction.

Drives the router's redaction step from the shared fixture at
``apcore-mcp/conformance/fixtures/output_redaction.json``. The TypeScript and
Rust bridges run the same fixture through their own routers; all three must
mask exactly the fields the output schema marks ``x-sensitive`` and leave
everything else alone.

All three delegate the masking itself to apcore's ``redact_sensitive``. What
this pins is the bridges' side of it: that the router applies it, applies it
with the module's output schema, and does not post-process the result.
"""

from __future__ import annotations

import pytest

from apcore_mcp.server.router import ExecutionRouter
from tests.conformance_fixtures import load_fixture

_FIXTURE = load_fixture("output_redaction.json")
_TOOL = "conformance.subject"


class _UnusedExecutor:
    """Redaction never reaches the executor; this stands in for one.

    The router probes the executor's call signatures at construction time, so
    the stub has to carry them even though redaction never invokes either.
    """

    async def call_async(self, module_id, inputs, context=None):  # pragma: no cover
        raise AssertionError("redaction must not execute the module")

    def call(self, module_id, inputs, context=None):  # pragma: no cover
        raise AssertionError("redaction must not execute the module")


@pytest.mark.parametrize("case", _FIXTURE["test_cases"], ids=lambda c: c["id"])
def test_conformance_output_redaction(case: dict):
    router = ExecutionRouter(
        _UnusedExecutor(),
        output_schema_map={_TOOL: case["output_schema"]},
    )
    original = dict(case["output"])

    redacted = router._maybe_redact(_TOOL, dict(case["output"]))

    assert redacted == case["expected_redacted_output"], f"{case['id']}: redaction mismatch"
    assert case["output"] == original, f"{case['id']}: the fixture input was mutated in place"
