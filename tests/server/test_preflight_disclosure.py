"""``__apcore_module_preview`` must not disclose module introspection to a denied caller.

apcore PROTOCOL_SPEC §12.8.5.1 (spec v1.13.0, apcore#96). ``Module.preflight()``
and ``Module.preview()`` are module-authored code, and what they return names
what the call would do: for a command-wrapping module the resolved binary and
its argv, for a writer the target of the side effect. This bridge serialises
``Executor.validate()``'s ``PreflightResult`` verbatim through
``_preflight_to_dict``, so whatever ``validate()`` puts in ``checks`` /
``predicted_changes`` reaches the MCP caller. Before apcore 0.27.0 ``validate()``
gated those hooks on module lookup alone -- pipeline Step 3 -- while the ACL
check is Step 4, so a denied caller ran module code and got back what it said.

These tests drive a REAL ``Executor`` over a REAL ``Registry`` and a REAL
``ACL``. A mocked executor would assert nothing: the gate lives inside
``validate()``.

Three of the eight cases are deliberately not denial cases. The allowed-caller
control exists because without it a bridge that never surfaced introspection at
all would pass every denial case for entirely the wrong reason; the
schema-failure case exists because the rule is about AUTHORIZATION, not
validity -- a caller the ACL permits is entitled to the module's account of what
would happen even when its inputs are malformed, which is what it needs in order
to fix the call.

Mirrors ``conformance/fixtures/preflight_disclosure.json`` in the apcore spec
repo, which pins the same four shapes on the SDKs themselves, and
``tests/server/preflightDisclosure.test.ts`` in apcore-mcp-typescript.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from apcore import ACL, Change, Config, Context, Identity, PreviewResult, Registry
from apcore.acl import ACLRule
from apcore.async_task import AsyncTaskManager
from apcore.executor import Executor
from apcore.module import Module, ModuleAnnotations
from apcore.schema.loader import SchemaLoader
from apcore_mcp.server.async_task_bridge import AsyncTaskBridge

# Sentinels chosen so that a plain substring search over the serialised envelope
# is a sufficient leak assertion: neither string can arise from any value the
# Executor computes on its own.
SENTINEL_BINARY = "/opt/apcore-sentinel-9f2c/bin/rm"
SENTINEL_TARGET = "/srv/customer-data-9f2c1e"

MODULE_ID = "danger.wipe"

# ``Module.input_schema`` is a Pydantic model class, so the JSON Schema goes
# through the same converter a real module's contract does. A raw dict is
# accepted but enforces nothing, which would make the schema-failure case below
# pass for the wrong reason.
_LOADER = SchemaLoader(Config({}))
_INPUT_SCHEMA = _LOADER.generate_model(
    {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    "PreflightDisclosureInput",
)
_OUTPUT_SCHEMA = _LOADER.generate_model({"type": "object", "properties": {}}, "PreflightDisclosureOutput")


class _SentinelModule(Module):
    """A destructive module whose introspection hooks name the binary and the path.

    ``hooks_invoked`` is recorded inside the hook bodies rather than inferred
    from the absent check entries: an implementation that runs the hooks and
    then discards their output has still run module-authored code on behalf of a
    caller the ACL denied, which is the side-effect half of the requirement.
    """

    input_schema = _INPUT_SCHEMA
    output_schema = _OUTPUT_SCHEMA
    description = "Deletes a directory tree"
    # Annotated so the ``requires_approval`` case below has something to
    # report. Governance annotations are metadata the ACL never reads, which is
    # exactly why they survive a denial -- see that test.
    annotations = ModuleAnnotations(requires_approval=True, destructive=True)

    def __init__(self) -> None:
        self.hooks_invoked: list[str] = []

    def execute(self, inputs: Any, context: Context | None = None) -> Any:
        raise AssertionError("validate() must never execute the module body")

    def preflight(self, inputs: Any, context: Context | None = None) -> list[str]:
        self.hooks_invoked.append("preflight")
        return [f"would run {SENTINEL_BINARY} -rf {SENTINEL_TARGET}"]

    def preview(self, inputs: Any, context: Context | None = None) -> PreviewResult:
        self.hooks_invoked.append("preview")
        return PreviewResult(
            changes=[
                Change(
                    action="delete",
                    target=SENTINEL_TARGET,
                    summary=f"{SENTINEL_BINARY} -rf {SENTINEL_TARGET}",
                )
            ]
        )


async def _preview(effect: str, inputs: dict[str, Any]) -> tuple[dict[str, Any], _SentinelModule]:
    """Drive the preview meta-tool over a real Executor.

    The rule's ``effect`` is what separates a permitted caller from a denied
    one, matching the spec fixture: a bridge-built ``Context`` is always
    top-level and apcore reserves ``Context.caller_id`` for ``child()``, so
    every MCP caller reaches the ACL as ``@external`` and ``callers: ["*"]`` is
    what a real deployment matches on.
    """
    registry = Registry()
    module = _SentinelModule()
    registry.register(MODULE_ID, module)

    acl = ACL(
        rules=[ACLRule(callers=["*"], targets=[MODULE_ID], effect=effect)],
        default_effect="allow" if effect == "deny" else "deny",
    )
    executor = Executor(registry, acl=acl)
    bridge = AsyncTaskBridge(AsyncTaskManager(executor))

    content, is_error, _ = await bridge.handle_meta_tool(
        "__apcore_module_preview",
        {"module_id": MODULE_ID, "arguments": inputs},
        router_extra={"identity": Identity(id="mcp.caller", type="module")},
    )
    assert is_error is False
    envelope: dict[str, Any] = json.loads(content[0]["text"])
    return envelope, module


async def _preview_denied() -> tuple[dict[str, Any], _SentinelModule]:
    return await _preview("deny", {"path": SENTINEL_TARGET})


def _check_names(envelope: dict[str, Any]) -> list[str]:
    return [c["check"] for c in envelope["checks"]]


def _failed_check_names(envelope: dict[str, Any]) -> list[str]:
    return [c["check"] for c in envelope["checks"] if not c["passed"]]


@pytest.mark.asyncio
async def test_preview_withholds_predicted_changes_when_acl_denies() -> None:
    envelope, _ = await _preview_denied()

    assert envelope["valid"] is False
    assert envelope["predicted_changes"] == []


@pytest.mark.asyncio
async def test_preview_emits_no_module_checks_when_acl_denies() -> None:
    envelope, _ = await _preview_denied()

    # Absent entirely, not present-and-empty: the presence of the entry is
    # itself the disclosure that the module implements the hook.
    assert "module_preflight" not in _check_names(envelope)
    assert "module_preview" not in _check_names(envelope)


@pytest.mark.asyncio
async def test_preview_leaks_no_binary_or_argv_when_acl_denies() -> None:
    envelope, _ = await _preview_denied()

    # The whole envelope, not just the fields checked above: a leak through a
    # check's ``warnings`` or an ACL diagnostic is the same leak.
    wire = json.dumps(envelope)
    assert SENTINEL_BINARY not in wire
    assert SENTINEL_TARGET not in wire


@pytest.mark.asyncio
async def test_preview_never_runs_module_hooks_when_acl_denies() -> None:
    _, module = await _preview_denied()

    assert module.hooks_invoked == []


@pytest.mark.asyncio
async def test_preview_still_reports_acl_as_the_only_failure_when_denied() -> None:
    envelope, _ = await _preview_denied()

    # §12.8.5.1 withholds introspection, not the denial reason. Exactly one
    # failure, because a second failed check could itself carry module detail.
    assert _failed_check_names(envelope) == ["acl"]


@pytest.mark.asyncio
async def test_preview_reports_requires_approval_when_acl_denies() -> None:
    """Deliberate, and pinned because apcore-mcp-rust diverges here.

    §12.8.5.1 withholds MODULE-AUTHORED introspection -- what ``preflight()``
    and ``preview()`` computed. ``requires_approval`` is neither: apcore
    resolves it from the module's declared annotations (or the
    ``ExecutionPolicy``) at a point before the disclosure gate, and the fixture
    ``preflight_disclosure.json`` deliberately asserts nothing about it.

    It is also not much of a disclosure: it says the module is approval-gated,
    not what the call would touch. Zeroing it would cost a denied caller the
    ability to distinguish "denied" from "denied AND would have needed approval
    anyway".
    """
    envelope, _ = await _preview_denied()

    assert envelope["requires_approval"] is True
    # ...while still disclosing nothing the module computed.
    assert envelope["predicted_changes"] == []


@pytest.mark.asyncio
async def test_preview_control_allowed_caller_receives_the_full_preview() -> None:
    """The control. Without it the denial cases above pass for the wrong reason."""
    envelope, module = await _preview("allow", {"path": SENTINEL_TARGET})

    assert envelope["valid"] is True
    assert module.hooks_invoked == ["preflight", "preview"]
    assert "module_preflight" in _check_names(envelope)
    assert "module_preview" in _check_names(envelope)
    assert len(envelope["predicted_changes"]) == 1
    assert envelope["predicted_changes"][0]["target"] == SENTINEL_TARGET
    assert SENTINEL_BINARY in json.dumps(envelope)


@pytest.mark.asyncio
async def test_preview_schema_failure_alone_does_not_withhold_the_preview() -> None:
    """The gate is scoped to authorization, not validity."""
    envelope, module = await _preview("allow", {})

    assert envelope["valid"] is False
    assert _failed_check_names(envelope) == ["schema"]
    assert module.hooks_invoked == ["preflight", "preview"]
    assert "module_preview" in _check_names(envelope)
    assert len(envelope["predicted_changes"]) == 1
