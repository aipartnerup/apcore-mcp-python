"""End-to-end: an ACL-sourced approval requirement gates a real MCP tools/call.

Every other `approval` test in this repo stops at the Config Bus parsing layer —
they prove the key is *accepted*, not that it *does* anything. This module
closes that gap by driving a real `apcore.Executor` (real `ACL`, real approval
handler, real module) through `ExecutionRouter.handle_call`, which is the exact
path a `tools/call` takes.

What is pinned here is the claim this bridge's 0.19.0 CHANGELOG makes —
"gating the call on a human decision even though the ACL itself allows it" —
at the MCP boundary rather than inside apcore:

- the module's own `requires_approval` annotation is **false**, so the ACL rule
  is the only possible source of an approval requirement;
- the rule is argument-scoped (`conditions.arguments.has_key`), so the same
  module is gated or not depending on what the call carries.

Cross-language counterparts: `tests/acl-approval-gating-e2e.test.ts`
(TypeScript) and `tests/acl_approval_gating_e2e.rs` (Rust).
"""

from __future__ import annotations

from typing import Any

import pytest
from apcore import Executor, Registry
from apcore.acl import ACL, ACLRule
from apcore.approval import ApprovalRequest, ApprovalResult
from mcp import types as mcp_types
from mcp.server.lowlevel import Server
from pydantic import AnyUrl, BaseModel

from apcore_mcp.server.factory import MCPServerFactory
from apcore_mcp.server.router import ExecutionRouter


class _Inputs(BaseModel):
    path: str
    recursive: bool | None = None


class _Outputs(BaseModel):
    deleted: str


class _DeleteModule:
    """A module that asks for no approval on its own account."""

    input_schema = _Inputs
    output_schema = _Outputs
    description = "Delete a path"
    # Deliberately false: any approval requirement observed in these tests can
    # only have come from the ACL rule, which is the whole point.
    annotations = {"requires_approval": False, "destructive": True}

    def execute(self, inputs: dict[str, Any], context: Any) -> dict[str, Any]:
        return {"deleted": inputs["path"]}


class _RecordingApprovalHandler:
    """Approves everything, but records what it was asked about."""

    def __init__(self) -> None:
        self.requests: list[ApprovalRequest] = []

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        self.requests.append(request)
        return ApprovalResult(status="approved", approved_by="test", approval_id="test-approval")

    async def check_approval(self, approval_id: str) -> ApprovalResult:
        return ApprovalResult(status="approved", approved_by="test", approval_id=approval_id)


def _build_router() -> tuple[ExecutionRouter, _RecordingApprovalHandler]:
    """A real executor whose only approval source is an argument-scoped ACL rule."""
    registry = Registry()
    registry.register("files.delete", _DeleteModule())

    acl = ACL(
        rules=[
            # Narrow rule first (first-match-wins, PROTOCOL_SPEC §6.3): a
            # recursive delete is allowed but must be put to a human.
            ACLRule(
                callers=["*"],
                targets=["files.delete"],
                effect="allow",
                approval="required",
                conditions={"arguments": {"has_key": ["recursive"]}},
            ),
            # Broad rule: everything else this caller does is allowed outright.
            ACLRule(callers=["*"], targets=["*"], effect="allow"),
        ],
        default_effect="deny",
    )

    handler = _RecordingApprovalHandler()
    executor = Executor(registry=registry, acl=acl, approval_handler=handler)
    return ExecutionRouter(executor), handler


@pytest.mark.asyncio
async def test_call_matching_the_argument_scoped_rule_is_gated() -> None:
    router, handler = _build_router()

    content, is_error, _trace = await router.handle_call("files.delete", {"path": "/tmp/x", "recursive": True})

    assert not is_error, f"approved call should succeed, got: {content}"
    assert len(handler.requests) == 1, (
        "a call carrying `recursive` matches the ACL rule's "
        "conditions.arguments.has_key and MUST reach the approval handler"
    )
    assert handler.requests[0].module_id == "files.delete"


@pytest.mark.asyncio
async def test_call_not_matching_the_rule_is_not_gated() -> None:
    router, handler = _build_router()

    content, is_error, _trace = await router.handle_call("files.delete", {"path": "/tmp/x"})

    assert not is_error, f"ungated call should succeed, got: {content}"
    assert handler.requests == [], (
        "a call without `recursive` does not match the approval rule and MUST NOT "
        "be put to a human — gating it would be the over-refusal §6.1.7 exists to prevent"
    )


# ---------------------------------------------------------------------------
# The same enforcement must hold on the `resources/read` path, which is the
# claim aiperceivable/apcore-mcp#15 makes: "Every `apcore://system.*` read
# dispatches through `ExecutionRouter.handle_call` -- never directly against
# the registry -- so ACL and audit apply identically to `tools/call` and
# `resources/read`."
#
# The shipped resource tests all drive a stub router, so they prove the read is
# *routed*; none of them proves the ACL actually *refuses*. A bypass here would
# be a management-surface disclosure, so it is asserted directly.
# ---------------------------------------------------------------------------


def _system_server(acl_effect: str) -> Server:
    """A real executor + real ACL, with the management resources registered."""
    from apcore.config import Config
    from apcore.sys_modules.registration import register_sys_modules

    registry = Registry()
    executor = Executor(registry=registry)
    register_sys_modules(
        registry=registry,
        executor=executor,
        config=Config(data={"sys_modules": {"enabled": True, "events": {"enabled": True, "subscribers": []}}}),
    )
    executor.set_acl(
        ACL(
            rules=[ACLRule(callers=["*"], targets=["system.*"], effect=acl_effect)],
            default_effect="deny",
        )
    )

    server = Server("acl-resource-read-test")
    MCPServerFactory().register_resource_handlers(server, registry, ExecutionRouter(executor))
    return server


async def _read(server: Server, uri: str) -> tuple[bool, str]:
    """Return (succeeded, rendered) for a `resources/read` of *uri*."""
    handler = server.request_handlers[mcp_types.ReadResourceRequest]
    request = mcp_types.ReadResourceRequest(
        method="resources/read",
        params=mcp_types.ReadResourceRequestParams(uri=AnyUrl(uri)),
    )
    try:
        result = await handler(request)
    except Exception as exc:  # noqa: BLE001 - the refusal path raises
        return False, f"{type(exc).__name__}: {exc}"
    return True, str(result.root)


@pytest.mark.asyncio
async def test_acl_allows_management_resource_read() -> None:
    """Control: an ACL that permits `system.*` lets the read through.

    Without this, the denial test below would pass just as happily against an
    adapter that never served the resource at all.
    """
    ok, rendered = await _read(_system_server("allow"), "apcore://system.health.summary")

    assert ok, f"an allowed caller must reach the management resource, got: {rendered}"
    assert "project" in rendered, f"expected real health output, got: {rendered[:200]}"


@pytest.mark.asyncio
async def test_acl_denial_blocks_management_resource_read() -> None:
    ok, rendered = await _read(_system_server("deny"), "apcore://system.health.summary")

    assert not ok, (
        "an ACL that denies system.* MUST refuse the resource read — reading a "
        f"management resource must not bypass the gate a tools/call passes. Got: {rendered[:300]}"
    )
