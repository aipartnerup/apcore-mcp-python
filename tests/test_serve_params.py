"""Tests for serve() tags, prefix, and log_level parameters."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apcore_mcp import serve
from tests.conftest import ModuleAnnotations, ModuleDescriptor

# ---------------------------------------------------------------------------
# Stub Registry / Executor (same pattern as test_api.py)
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal Registry stub with list() and get_definition()."""

    def __init__(self, descriptors: list[ModuleDescriptor] | None = None):
        self._descriptors = {d.module_id: d for d in (descriptors or [])}

    def list(self, tags=None, prefix=None):
        ids = list(self._descriptors.keys())
        if prefix is not None:
            ids = [mid for mid in ids if mid.startswith(prefix)]
        if tags is not None:
            tag_set = set(tags)
            ids = [mid for mid in ids if tag_set.issubset(set(self._descriptors[mid].tags))]
        return sorted(ids)

    def get_definition(self, module_id):
        return self._descriptors.get(module_id)


class StubExecutor:
    """Minimal Executor stub with call_async() and registry attribute."""

    def __init__(self, registry: StubRegistry):
        self.registry = registry

    async def call_async(self, _module_id: str, _inputs: dict | None = None) -> dict:
        return {"ok": True}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_descriptors() -> list[ModuleDescriptor]:
    return [
        ModuleDescriptor(
            module_id="image.resize",
            description="Resize an image",
            input_schema={
                "type": "object",
                "properties": {
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
                "required": ["width", "height"],
            },
            output_schema={"type": "object"},
            tags=["image"],
            annotations=ModuleAnnotations(idempotent=True),
        ),
        ModuleDescriptor(
            module_id="text.echo",
            description="Echo text",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            output_schema={"type": "object"},
            tags=["text"],
        ),
    ]


@pytest.fixture
def registry(sample_descriptors) -> StubRegistry:
    return StubRegistry(sample_descriptors)


# ===========================================================================
# Tests for serve() tags and prefix parameters
# ===========================================================================


class TestServeTagsPrefix:
    """Tests for serve() tags and prefix filtering parameters."""

    def _patch_server(self):
        """Return a context manager that patches factory and transport."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            with (
                patch("apcore_mcp.TransportManager") as mock_tm_cls,
                patch("apcore_mcp.MCPServerFactory") as mock_factory_cls,
                patch("apcore_mcp.ExecutionRouter"),
            ):
                mock_factory = mock_factory_cls.return_value
                mock_factory.create_server.return_value = MagicMock()
                mock_factory.build_tools.return_value = []
                mock_factory.build_init_options.return_value = MagicMock()

                mock_tm = mock_tm_cls.return_value
                mock_tm.run_stdio = AsyncMock()

                yield mock_factory

        return _ctx()

    def test_build_tools_called_with_tags_and_prefix(self, registry):
        """When tags and prefix are provided, build_tools receives them."""
        with self._patch_server() as mock_factory:
            serve(registry, tags=["image"], prefix="image.")

            mock_factory.build_tools.assert_called_once_with(registry, tags=["image"], prefix="image.")

    def test_build_tools_called_with_tags_only(self, registry):
        """When only tags is provided, prefix defaults to None."""
        with self._patch_server() as mock_factory:
            serve(registry, tags=["text"])

            mock_factory.build_tools.assert_called_once_with(registry, tags=["text"], prefix=None)

    def test_build_tools_called_with_prefix_only(self, registry):
        """When only prefix is provided, tags defaults to None."""
        with self._patch_server() as mock_factory:
            serve(registry, prefix="text")

            mock_factory.build_tools.assert_called_once_with(registry, tags=None, prefix="text")

    def test_build_tools_called_without_tags_or_prefix(self, registry):
        """When neither tags nor prefix is provided, both default to None."""
        with self._patch_server() as mock_factory:
            serve(registry)

            mock_factory.build_tools.assert_called_once_with(registry, tags=None, prefix=None)


# ===========================================================================
# Tests for serve() log_level parameter
# ===========================================================================


class TestServeLogLevel:
    """Tests for serve() log_level parameter."""

    def _patch_server(self):
        """Return a context manager that patches factory and transport."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            with (
                patch("apcore_mcp.TransportManager") as mock_tm_cls,
                patch("apcore_mcp.MCPServerFactory") as mock_factory_cls,
                patch("apcore_mcp.ExecutionRouter"),
            ):
                mock_factory = mock_factory_cls.return_value
                mock_factory.create_server.return_value = MagicMock()
                mock_factory.build_tools.return_value = []
                mock_factory.build_init_options.return_value = MagicMock()

                mock_tm = mock_tm_cls.return_value
                mock_tm.run_stdio = AsyncMock()

                yield mock_factory

        return _ctx()

    def test_log_level_applies_package_logger(self, registry):
        """When log_level is provided, the apcore_mcp logger level is set."""
        with self._patch_server(), patch("apcore_mcp.logging.getLogger") as mock_get_logger:
            mock_logger = mock_get_logger.return_value
            serve(registry, log_level="DEBUG")

            mock_get_logger.assert_called_with("apcore_mcp")
            mock_logger.setLevel.assert_called_once_with(logging.DEBUG)

    def test_log_level_case_insensitive(self, registry):
        """log_level is case-insensitive ('info' works like 'INFO')."""
        with self._patch_server(), patch("apcore_mcp.logging.getLogger") as mock_get_logger:
            mock_logger = mock_get_logger.return_value
            serve(registry, log_level="info")

            mock_get_logger.assert_called_with("apcore_mcp")
            mock_logger.setLevel.assert_called_once_with(logging.INFO)

    def test_log_level_not_applied_when_none(self, registry):
        """When log_level is None (default), the package logger level is not changed."""
        with self._patch_server(), patch("apcore_mcp.logging.getLogger") as mock_get_logger:
            mock_logger = mock_get_logger.return_value
            serve(registry)

            mock_logger.setLevel.assert_not_called()

    def test_log_level_warning(self, registry):
        """log_level='WARNING' sets WARNING level."""
        with self._patch_server(), patch("apcore_mcp.logging.getLogger") as mock_get_logger:
            mock_logger = mock_get_logger.return_value
            serve(registry, log_level="WARNING")

            mock_get_logger.assert_called_with("apcore_mcp")
            mock_logger.setLevel.assert_called_once_with(logging.WARNING)
