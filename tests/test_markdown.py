"""Tests for the apcore-toolkit Markdown bridge (apcore_mcp.markdown).

Covers the [A-D-MD-3] never-raises contract, the [A-D-MD-5] memoized
availability probe, and the [A-D-MD-8] ScannedModule field set.
"""

from __future__ import annotations

import builtins
from typing import Any

import pytest
from apcore_mcp import markdown as md


@pytest.fixture(autouse=True)
def _clear_availability_cache() -> Any:
    """is_available is memoized; keep the cache from leaking across tests."""
    md.is_available.cache_clear()
    yield
    md.is_available.cache_clear()


def _block_toolkit_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `from apcore_toolkit import ...` raise ImportError."""
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "apcore_toolkit" or name.startswith("apcore_toolkit."):
            raise ImportError("No module named 'apcore_toolkit'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


# ---------------------------------------------------------------------------
# [A-D-MD-3] render_module_markdown returns None instead of raising
# ---------------------------------------------------------------------------


class TestADMD3NeverRaises:
    """The contract is `str | None`, "On toolkit unavailable: None", never raises."""

    def test_returns_none_when_toolkit_is_missing(
        self, simple_descriptor: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _block_toolkit_import(monkeypatch)

        assert md.render_module_markdown(simple_descriptor) is None

    def test_or_fallback_idiom_works(self, simple_descriptor: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """The spec-sanctioned `render(d) or d.description` must not blow up."""
        _block_toolkit_import(monkeypatch)

        assert (md.render_module_markdown(simple_descriptor) or simple_descriptor.description) == (
            simple_descriptor.description
        )

    def test_returns_none_when_format_module_raises(
        self, simple_descriptor: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import apcore_toolkit

        def boom(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("toolkit exploded")

        monkeypatch.setattr(apcore_toolkit, "format_module", boom)

        assert md.render_module_markdown(simple_descriptor) is None

    def test_returns_none_when_format_module_returns_a_non_string(
        self, simple_descriptor: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import apcore_toolkit

        monkeypatch.setattr(apcore_toolkit, "format_module", lambda *a, **k: {"style": "json"})

        assert md.render_module_markdown(simple_descriptor) is None

    def test_renders_markdown_when_the_toolkit_is_present(self, simple_descriptor: Any) -> None:
        rendered = md.render_module_markdown(simple_descriptor)

        assert isinstance(rendered, str)
        assert rendered.startswith("# ")


# ---------------------------------------------------------------------------
# [A-D-MD-5] is_available is memoized and probes the renderer
# ---------------------------------------------------------------------------


class TestADMD5IsAvailable:
    """Result MUST be cached after the first resolution; subsequent calls do not re-import."""

    def test_result_is_cached_after_the_first_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        real_import = builtins.__import__

        def counting_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "apcore_toolkit":
                calls.append(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", counting_import)

        assert md.is_available() is True
        assert md.is_available() is True
        assert md.is_available() is True

        assert len(calls) == 1

    def test_reports_false_when_the_toolkit_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _block_toolkit_import(monkeypatch)

        assert md.is_available() is False

    def test_reports_false_when_the_renderer_is_not_callable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A broken install resolves the package but not a usable format_module."""
        import apcore_toolkit

        monkeypatch.setattr(apcore_toolkit, "format_module", "not callable")

        assert md.is_available() is False


# ---------------------------------------------------------------------------
# [A-D-MD-8] descriptor_to_scanned_module field set
# ---------------------------------------------------------------------------


class TestADMD8ScannedModuleFields:
    """suggested_alias and warnings are set by the TS and Rust adapters too."""

    def test_suggested_alias_and_warnings_are_populated(self, simple_descriptor: Any) -> None:
        scanned = md.descriptor_to_scanned_module(simple_descriptor)

        assert scanned.suggested_alias is None
        assert scanned.warnings == []

    def test_construction_survives_a_toolkit_without_defaults(
        self, simple_descriptor: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ScannedModule declaring `warnings` with no default must still build."""
        import dataclasses

        import apcore_toolkit

        real = apcore_toolkit.ScannedModule

        @dataclasses.dataclass
        class NoDefaults:
            module_id: str
            description: str
            input_schema: dict[str, Any]
            output_schema: dict[str, Any]
            tags: list[str]
            target: str
            version: str
            annotations: Any
            documentation: str | None
            suggested_alias: str | None
            examples: list[Any]
            metadata: dict[str, Any]
            warnings: list[str]
            display: Any

        monkeypatch.setattr(apcore_toolkit, "ScannedModule", NoDefaults)
        try:
            scanned = md.descriptor_to_scanned_module(simple_descriptor)
        finally:
            monkeypatch.setattr(apcore_toolkit, "ScannedModule", real)

        assert isinstance(scanned, NoDefaults)
        assert scanned.warnings == []
        assert scanned.suggested_alias is None
