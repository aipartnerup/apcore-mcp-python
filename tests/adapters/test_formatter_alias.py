"""Regression test for EM-1: McpErrorFormatter canonical alias (CHANGELOG 0.14.0).

Both names must be importable from apcore_mcp and apcore_mcp.adapters.
"""

from __future__ import annotations


def test_McpErrorFormatter_importable_from_package_root():
    """McpErrorFormatter must be importable from the top-level package."""
    from apcore_mcp import McpErrorFormatter  # noqa: F401


def test_McpErrorFormatter_importable_from_adapters():
    """McpErrorFormatter must be importable from apcore_mcp.adapters."""
    from apcore_mcp.adapters import McpErrorFormatter  # noqa: F401


def test_McpErrorFormatter_is_alias_for_MCPErrorFormatter():
    """McpErrorFormatter must refer to the same class as MCPErrorFormatter."""
    from apcore_mcp import McpErrorFormatter, MCPErrorFormatter

    assert McpErrorFormatter is MCPErrorFormatter


def test_McpErrorFormatter_in_package_all():
    """McpErrorFormatter must be in apcore_mcp.__all__."""
    import apcore_mcp

    assert "McpErrorFormatter" in apcore_mcp.__all__


def test_McpErrorFormatter_in_adapters_all():
    """McpErrorFormatter must be in apcore_mcp.adapters.__all__."""
    import apcore_mcp.adapters

    assert "McpErrorFormatter" in apcore_mcp.adapters.__all__
