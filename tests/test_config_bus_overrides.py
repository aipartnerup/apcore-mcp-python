"""[D9-002] Regression tests for ``_load_config_bus_overrides`` helper.

The helper replaces a ~60-line block previously duplicated in both
``serve()`` and ``async_serve()``. These tests pin the contract so future
refactors cannot silently drop a scalar override or accidentally diverge
the two callers.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import pytest

import apcore_mcp


class _FakeRegistry:
    """Minimal placeholder — the helper only forwards it to build_strategy_from_config."""


class _FakeConfig:
    """Minimal ``apcore.Config`` stand-in exposing ``.get(key)``."""

    def __init__(self, store: dict[str, Any]) -> None:
        self._store = store

    def get(self, key: str) -> Any:
        return self._store.get(key)


@pytest.fixture
def fake_registry() -> _FakeRegistry:
    return _FakeRegistry()


class TestLoadConfigBusOverridesScalars:
    """The 9 scalar keys round-trip through the helper as expected."""

    def test_all_scalars_propagate(self, fake_registry: _FakeRegistry) -> None:
        store = {
            "mcp.transport": "streamable-http",
            "mcp.host": "0.0.0.0",
            "mcp.port": 9000,
            "mcp.name": "configured-name",
            "mcp.log_level": "DEBUG",
            "mcp.validate_inputs": True,
            "mcp.explorer": True,
            "mcp.explorer_prefix": "/ui",
            "mcp.require_auth": False,
        }
        fake_cfg = _FakeConfig(store)

        with patch("apcore.Config") as mock_cfg_cls:
            mock_cfg_cls.load.return_value = fake_cfg
            result = apcore_mcp._load_config_bus_overrides(
                registry=fake_registry,
                strategy=None,
                load_pipeline=False,
            )

        scalars = cast(dict[str, Any], result["scalars"])
        assert scalars["transport"] == "streamable-http"
        assert scalars["host"] == "0.0.0.0"
        assert scalars["port"] == 9000
        assert scalars["name"] == "configured-name"
        assert scalars["log_level"] == "DEBUG"
        assert scalars["validate_inputs"] is True
        assert scalars["explorer"] is True
        assert scalars["explorer_prefix"] == "/ui"
        assert scalars["require_auth"] is False

    def test_port_string_coerced_to_int(self, fake_registry: _FakeRegistry) -> None:
        """``mcp.port`` may arrive as a string from env vars — coerce to int."""
        fake_cfg = _FakeConfig({"mcp.port": "8080"})
        with patch("apcore.Config") as mock_cfg_cls:
            mock_cfg_cls.load.return_value = fake_cfg
            result = apcore_mcp._load_config_bus_overrides(
                registry=fake_registry,
                strategy=None,
                load_pipeline=False,
            )
        assert cast(dict[str, Any], result["scalars"])["port"] == 8080

    def test_port_garbage_string_is_ignored(self, fake_registry: _FakeRegistry) -> None:
        fake_cfg = _FakeConfig({"mcp.port": "not-a-number"})
        with patch("apcore.Config") as mock_cfg_cls:
            mock_cfg_cls.load.return_value = fake_cfg
            result = apcore_mcp._load_config_bus_overrides(
                registry=fake_registry,
                strategy=None,
                load_pipeline=False,
            )
        assert "port" not in cast(dict[str, Any], result["scalars"])

    def test_empty_config_returns_empty_scalars(self, fake_registry: _FakeRegistry) -> None:
        fake_cfg = _FakeConfig({})
        with patch("apcore.Config") as mock_cfg_cls:
            mock_cfg_cls.load.return_value = fake_cfg
            result = apcore_mcp._load_config_bus_overrides(
                registry=fake_registry,
                strategy=None,
                load_pipeline=False,
            )
        assert result["scalars"] == {}
        assert result["config_middleware"] == []
        assert result["config_acl"] is None
        assert result["pipeline_strategy"] is None

    def test_missing_apcore_returns_blank_envelope(self, fake_registry: _FakeRegistry) -> None:
        """No apcore install ⇒ helper returns blank dict, never raises."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "apcore":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = apcore_mcp._load_config_bus_overrides(
                registry=fake_registry,
                strategy=None,
                load_pipeline=True,
            )
        assert result["scalars"] == {}
        assert result["config_middleware"] == []
        assert result["config_acl"] is None
        assert result["pipeline_strategy"] is None


class TestLoadConfigBusOverridesPipelineFlag:
    """``load_pipeline=False`` matches the historical async_serve() behaviour."""

    def test_pipeline_skipped_when_flag_false(self, fake_registry: _FakeRegistry) -> None:
        fake_cfg = _FakeConfig({"mcp.pipeline": {"name": "standard"}})
        with patch("apcore.Config") as mock_cfg_cls, patch("apcore.build_strategy_from_config") as mock_build:
            mock_cfg_cls.load.return_value = fake_cfg
            mock_build.return_value = "BUILT"
            result = apcore_mcp._load_config_bus_overrides(
                registry=fake_registry,
                strategy=None,
                load_pipeline=False,
            )
        assert result["pipeline_strategy"] is None
        mock_build.assert_not_called()

    def test_pipeline_consumed_when_flag_true(self, fake_registry: _FakeRegistry) -> None:
        fake_cfg = _FakeConfig({"mcp.pipeline": {"name": "standard"}})
        with patch("apcore.Config") as mock_cfg_cls, patch("apcore.build_strategy_from_config") as mock_build:
            mock_cfg_cls.load.return_value = fake_cfg
            mock_build.return_value = "BUILT"
            result = apcore_mcp._load_config_bus_overrides(
                registry=fake_registry,
                strategy=None,
                load_pipeline=True,
            )
        assert result["pipeline_strategy"] == "BUILT"
        mock_build.assert_called_once()
