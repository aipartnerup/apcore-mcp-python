"""Cross-language conformance: the nine canonical system.* modules -> exact MCP primitive.

Drives ``MCPServerFactory.build_tools`` / ``register_resource_handlers`` from
the shared fixture at ``apcore-mcp/conformance/fixtures/system_surface.json``,
against a registry built by a REAL ``apcore.sys_modules.register_sys_modules``
call. The TypeScript and Rust bridges run the identical fixture through their
own factories against their own real ``registerSysModules`` /
``register_sys_modules``; all three must agree byte-for-byte on which module
ids become tools, which become resources, which become resource templates,
and the exact name/URI each one gets (aiperceivable/apcore-mcp#15's
"byte-identical tools/list, resources/list, resources/templates/list"
acceptance criterion).
"""

from __future__ import annotations

from typing import Any

import pytest
from apcore import Executor, Registry
from apcore.config import Config
from apcore.sys_modules.registration import register_sys_modules
from mcp.server.lowlevel import Server

from apcore_mcp.server import factory as factory_module
from apcore_mcp.server.factory import MCPServerFactory
from tests.conformance_fixtures import load_fixture

_FIXTURE = load_fixture("system_surface.json")

pytestmark = pytest.mark.skipif(_FIXTURE is None, reason="shared conformance fixtures not available locally")


class _StubRouter:
    async def handle_call(self, name: str, arguments: dict[str, Any], extra: Any = None) -> Any:
        raise AssertionError("this conformance test only lists tools/resources; it never reads one")


@pytest.fixture()
def real_registry() -> Registry:
    registry = Registry()
    executor = Executor(registry=registry)
    config = Config(data=_FIXTURE["setup"]["config"])
    register_sys_modules(registry=registry, executor=executor, config=config)
    return registry


def test_control_modules_are_tools(real_registry: Registry) -> None:
    """The `system.*` tool set must equal the fixture's exactly — not merely contain it.

    A subset assertion would let an adapter emit an *extra* management tool and
    still pass, which is the divergence direction this fixture exists to catch
    (aiperceivable/apcore-mcp#15 asks for byte-identical `tools/list` across the
    three bridges, not "at least these").
    """
    tools = MCPServerFactory().build_tools(real_registry)
    system_tool_names = {t.name for t in tools if t.name.startswith("system.")}
    expected = {t["name"] for t in _FIXTURE["tools"]}

    assert system_tool_names == expected, (
        f"system.* tools/list set mismatch\n  extra:   {sorted(system_tool_names - expected)}"
        f"\n  missing: {sorted(expected - system_tool_names)}"
    )


def test_readonly_system_modules_are_not_tools(real_registry: Registry) -> None:
    tools = MCPServerFactory().build_tools(real_registry)
    tool_names = {t.name for t in tools}

    for module_id in _FIXTURE["not_tools"]:
        assert module_id not in tool_names, f"{module_id} must not be projected as a tool"


async def test_readonly_system_modules_are_resources_and_templates(real_registry: Registry) -> None:
    server = Server("conformance-test")
    MCPServerFactory().register_resource_handlers(server, real_registry, _StubRouter())

    list_resources = server.request_handlers[factory_module.mcp_types.ListResourcesRequest]
    resources = (await list_resources(None)).root.resources
    # Only the `apcore://` scheme is this fixture's contract; `docs://` resources
    # legitimately vary with how many registered modules carry documentation.
    apcore_uris = {str(r.uri) for r in resources if str(r.uri).startswith("apcore://")}
    expected_uris = {r["uri"] for r in _FIXTURE["resources"]}

    assert apcore_uris == expected_uris, (
        f"apcore:// resources/list set mismatch\n  extra:   {sorted(apcore_uris - expected_uris)}"
        f"\n  missing: {sorted(expected_uris - apcore_uris)}"
    )

    list_templates = server.request_handlers[factory_module.mcp_types.ListResourceTemplatesRequest]
    templates = (await list_templates(None)).root.resourceTemplates
    template_uris = {t.uriTemplate for t in templates if t.uriTemplate.startswith("apcore://")}
    expected_templates = {t["uri_template"] for t in _FIXTURE["resource_templates"]}

    assert template_uris == expected_templates, (
        f"apcore:// resources/templates/list set mismatch"
        f"\n  extra:   {sorted(template_uris - expected_templates)}"
        f"\n  missing: {sorted(expected_templates - template_uris)}"
    )
