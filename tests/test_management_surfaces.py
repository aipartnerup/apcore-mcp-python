"""Tests for aiperceivable/apcore-mcp#15(b) and #16 Phase A:

- ``_compute_management_surfaces`` — scanning a registry for the four
  ``system.*`` management surfaces (health/usage/manifest/control).
- ``_warn_if_unprotected_control_surface`` — the advisory startup WARN when
  ``system.control.*`` modules are registered with no recognised gate.
- End-to-end: ``APCoreMCP._build_server_components()`` wires both into the
  real ``initialize`` capabilities and the real startup log, using a real
  apcore ``Registry``/``Executor``/``register_sys_modules``.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from apcore_mcp.apcore_mcp import _compute_management_surfaces, _warn_if_unprotected_control_surface

# ---------------------------------------------------------------------------
# _compute_management_surfaces — unit tests
# ---------------------------------------------------------------------------


class StubRegistry:
    def __init__(self, module_ids: list[str]) -> None:
        self._ids = list(module_ids)

    def list(self, tags=None, prefix=None):
        return list(self._ids)


class TestComputeManagementSurfaces:
    def test_all_present(self) -> None:
        registry = StubRegistry(
            [
                "system.health.summary",
                "system.usage.summary",
                "system.manifest.full",
                "system.control.reload_module",
            ]
        )
        assert _compute_management_surfaces(registry) == {
            "health": True,
            "usage": True,
            "manifest": True,
            "control": True,
        }

    def test_none_present(self) -> None:
        registry = StubRegistry(["image.resize", "text.echo"])
        assert _compute_management_surfaces(registry) == {
            "health": False,
            "usage": False,
            "manifest": False,
            "control": False,
        }

    def test_partial_presence(self) -> None:
        registry = StubRegistry(["system.health.module", "other.tool"])
        surfaces = _compute_management_surfaces(registry)
        assert surfaces["health"] is True
        assert surfaces["usage"] is False
        assert surfaces["manifest"] is False
        assert surfaces["control"] is False

    def test_empty_registry(self) -> None:
        registry = StubRegistry([])
        assert _compute_management_surfaces(registry) == {
            "health": False,
            "usage": False,
            "manifest": False,
            "control": False,
        }


# ---------------------------------------------------------------------------
# _warn_if_unprotected_control_surface — unit tests
# ---------------------------------------------------------------------------


def _fake_governance_state(**overrides: Any) -> SimpleNamespace:
    defaults = {
        "control_modules_registered": True,
        "read_modules_registered": True,
        "acl_configured": False,
        "builtin_acl_gate_wired": False,
        "approval_handler_configured": False,
        "builtin_approval_gate_wired": False,
        "policy_strict": False,
        "all_control_modules_require_approval": False,
        "unprotected_control_surface": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class StubExecutorWithGovernance:
    def __init__(self, state: SimpleNamespace) -> None:
        self._state = state

    def governance_state(self) -> SimpleNamespace:
        return self._state


class StubExecutorWithoutGovernance:
    """Mimics an older apcore Executor / test double with no governance_state()."""


class TestWarnIfUnprotectedControlSurface:
    def test_warns_when_unprotected(self, caplog: pytest.LogCaptureFixture) -> None:
        executor = StubExecutorWithGovernance(_fake_governance_state())
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.apcore_mcp"):
            _warn_if_unprotected_control_surface(executor)
        assert "UNPROTECTED MANAGEMENT SURFACE" in caplog.text
        assert "No ACL is configured" in caplog.text
        assert "No approval handler is configured" in caplog.text
        assert "Not every registered system.control.* module declares requires_approval=True" in caplog.text
        warn_records = [r for r in caplog.records if "UNPROTECTED MANAGEMENT SURFACE" in r.message]
        assert len(warn_records) == 1
        assert warn_records[0].levelno == logging.WARNING

    def test_no_warning_when_protected(self, caplog: pytest.LogCaptureFixture) -> None:
        executor = StubExecutorWithGovernance(_fake_governance_state(unprotected_control_surface=False))
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.apcore_mcp"):
            _warn_if_unprotected_control_surface(executor)
        assert "UNPROTECTED MANAGEMENT SURFACE" not in caplog.text

    def test_no_warning_when_no_control_modules(self, caplog: pytest.LogCaptureFixture) -> None:
        executor = StubExecutorWithGovernance(
            _fake_governance_state(control_modules_registered=False, unprotected_control_surface=False)
        )
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.apcore_mcp"):
            _warn_if_unprotected_control_surface(executor)
        assert "UNPROTECTED MANAGEMENT SURFACE" not in caplog.text

    def test_acl_wired_but_gate_missing_names_the_right_gap(self, caplog: pytest.LogCaptureFixture) -> None:
        executor = StubExecutorWithGovernance(
            _fake_governance_state(acl_configured=True, builtin_acl_gate_wired=False)
        )
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.apcore_mcp"):
            _warn_if_unprotected_control_surface(executor)
        assert "does not include the built-in ACL gate" in caplog.text
        assert "No ACL is configured" not in caplog.text

    def test_no_exception_and_no_warning_for_executor_without_governance_state(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        executor = StubExecutorWithoutGovernance()
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.apcore_mcp"):
            _warn_if_unprotected_control_surface(executor)  # must not raise
        assert "UNPROTECTED MANAGEMENT SURFACE" not in caplog.text

    def test_no_exception_when_governance_state_raises(self, caplog: pytest.LogCaptureFixture) -> None:
        class RaisingExecutor:
            def governance_state(self):
                raise RuntimeError("boom")

        with caplog.at_level(logging.WARNING, logger="apcore_mcp.apcore_mcp"):
            _warn_if_unprotected_control_surface(RaisingExecutor())  # must not raise
        assert "UNPROTECTED MANAGEMENT SURFACE" not in caplog.text


# ---------------------------------------------------------------------------
# End-to-end: real apcore Registry/Executor + register_sys_modules, wired
# through APCoreMCP._build_server_components()
# ---------------------------------------------------------------------------


def _sys_modules_config(*, events_enabled: bool = True):
    from apcore.config import Config

    return Config(
        data={
            "sys_modules": {
                "enabled": True,
                "events": {"enabled": events_enabled, "subscribers": []},
            },
        }
    )


class TestEndToEndWithRealApcore:
    def test_unprotected_system_control_warns_on_build(self, caplog: pytest.LogCaptureFixture) -> None:
        from apcore import Executor, Registry
        from apcore.sys_modules.registration import register_sys_modules

        from apcore_mcp.apcore_mcp import APCoreMCP

        registry = Registry()
        executor = Executor(registry=registry)
        register_sys_modules(registry=registry, executor=executor, config=_sys_modules_config())

        mcp = APCoreMCP(executor, async_tasks=False)
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.apcore_mcp"):
            server, router, tools, init_options, version = mcp._build_server_components()

        assert "UNPROTECTED MANAGEMENT SURFACE" in caplog.text

        # And the capability was still advertised correctly regardless of the warning.
        dumped = init_options.capabilities.model_dump(exclude_none=True)
        ext = dumped["extensions"]["com.aiperceivable/management"]
        assert set(ext["surfaces"]) == {"health", "usage", "manifest", "control"}

        # Read-only system.* modules must not appear as tools.
        tool_names = {t.name for t in tools}
        assert not any(name.startswith(("system.health.", "system.usage.", "system.manifest.")) for name in tool_names)
        assert "system.control.reload_module" in tool_names

    def test_acl_protected_control_surface_does_not_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        from apcore import ACL, ACLRule, Executor, Registry
        from apcore.sys_modules.registration import register_sys_modules

        from apcore_mcp.apcore_mcp import APCoreMCP

        registry = Registry()
        executor = Executor(registry=registry)
        register_sys_modules(registry=registry, executor=executor, config=_sys_modules_config())

        acl = ACL(
            rules=[
                ACLRule(callers=["@external"], targets=["system.*"], effect="deny"),
            ],
            default_effect="deny",
        )
        executor.set_acl(acl)

        mcp = APCoreMCP(executor, async_tasks=False)
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.apcore_mcp"):
            mcp._build_server_components()

        assert "UNPROTECTED MANAGEMENT SURFACE" not in caplog.text

    def test_no_sys_modules_registered_no_warning_no_extension(self, caplog: pytest.LogCaptureFixture) -> None:
        from apcore import Executor, Registry

        from apcore_mcp.apcore_mcp import APCoreMCP

        registry = Registry()
        executor = Executor(registry=registry)

        mcp = APCoreMCP(executor, async_tasks=False)
        with caplog.at_level(logging.WARNING, logger="apcore_mcp.apcore_mcp"):
            _server, _router, _tools, init_options, _version = mcp._build_server_components()

        assert "UNPROTECTED MANAGEMENT SURFACE" not in caplog.text
        dumped = init_options.capabilities.model_dump(exclude_none=True)
        assert "extensions" not in dumped

    async def test_client_ignorant_of_extension_still_accesses_management_surface(self) -> None:
        """A client that never inspects `capabilities.extensions` still gets a
        fully-functional tools list and resource handlers -- the extension is
        purely additive discovery, never a behaviour gate (aiperceivable/apcore-mcp#16)."""
        from apcore import Executor, Registry
        from apcore.sys_modules.registration import register_sys_modules
        from mcp import types as mcp_types

        from apcore_mcp.apcore_mcp import APCoreMCP

        registry = Registry()
        executor = Executor(registry=registry)
        register_sys_modules(registry=registry, executor=executor, config=_sys_modules_config())

        mcp = APCoreMCP(executor, async_tasks=False)
        server, router, tools, init_options, version = mcp._build_server_components()

        # Tool call path: system.control.* remains callable as a Tool regardless
        # of whether the connecting client ever looked at `capabilities.extensions`.
        tool_names = {t.name for t in tools}
        assert "system.control.reload_module" in tool_names

        # Resource path: read-only system.* modules are reachable as resources.
        list_resources = server.request_handlers[mcp_types.ListResourcesRequest]
        result = (await list_resources(None)).root
        uris = {str(r.uri) for r in result.resources}
        assert "apcore://system.health.summary" in uris
