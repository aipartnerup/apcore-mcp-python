"""Markdown rendering for apcore modules via apcore-toolkit.

LLMs read MCP/OpenAI tool ``description`` strings as their primary signal
for tool selection — the richer the description, the better the agent
selects the right tool. apcore-toolkit's ``format_module(style="markdown")``
emits a canonical, cross-SDK-byte-equivalent rendering with title,
description, tags, behavior table (annotations), schemas, and examples.

This module bridges apcore's :class:`ModuleDescriptor` (the runtime type
flowing through apcore-mcp) to apcore-toolkit's :class:`ScannedModule`
(the input format ``format_module`` expects), then delegates to the
toolkit. ``apcore-toolkit`` is an optional dependency installed via the
``[markdown]`` extra; callers should check :func:`is_available` before
invoking :func:`render_module_markdown`.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

__all__ = [
    "is_available",
    "render_module_markdown",
    "descriptor_to_scanned_module",
]


def is_available() -> bool:
    """Return True when apcore-toolkit is installed and importable."""
    import importlib.util

    return importlib.util.find_spec("apcore_toolkit") is not None


def descriptor_to_scanned_module(descriptor: Any) -> Any:
    """Adapt an apcore :class:`ModuleDescriptor` to a toolkit ``ScannedModule``.

    The two types are near-supersets of each other — this helper copies
    the overlapping fields and supplies sensible defaults (empty
    ``target``, no ``documentation``) for the toolkit-only ones.

    Raises ``ImportError`` when apcore-toolkit is not installed.
    """
    from apcore_toolkit import ScannedModule

    target = getattr(descriptor, "target", "") or ""
    documentation = getattr(descriptor, "documentation", None)
    examples = list(getattr(descriptor, "examples", None) or [])
    metadata = dict(getattr(descriptor, "metadata", None) or {})
    display = getattr(descriptor, "display", None)
    annotations = getattr(descriptor, "annotations", None)
    version = getattr(descriptor, "version", None) or "1.0.0"
    tags = list(getattr(descriptor, "tags", None) or [])

    # Build kwargs robustly: only pass fields the installed toolkit
    # actually accepts (forwards-compatible across minor versions that
    # add or remove fields).
    candidate_kwargs: dict[str, Any] = {
        "module_id": descriptor.module_id,
        "description": getattr(descriptor, "description", "") or "",
        "input_schema": getattr(descriptor, "input_schema", None) or {},
        "output_schema": getattr(descriptor, "output_schema", None) or {},
        "tags": tags,
        "target": target,
        "version": version,
        "annotations": annotations,
        "documentation": documentation,
        "examples": examples,
        "metadata": metadata,
        "display": display,
    }
    if is_dataclass(ScannedModule):
        accepted = {f.name for f in fields(ScannedModule)}
        candidate_kwargs = {k: v for k, v in candidate_kwargs.items() if k in accepted}
    return ScannedModule(**candidate_kwargs)


def render_module_markdown(descriptor: Any, *, display: bool = True) -> str:
    """Render a :class:`ModuleDescriptor` as canonical apcore-toolkit markdown.

    Returns the markdown body produced by
    ``apcore_toolkit.format_module(scanned, style="markdown")`` — title,
    description, tags, behavior table (only fields differing from
    defaults — toolkit 0.6.0 alignment), JSON Schema for input/output,
    and examples.

    Args:
        descriptor: An apcore ``ModuleDescriptor`` (duck-typed).
        display: Honour the ``display`` overlay when present (default True).

    Raises:
        ImportError: when apcore-toolkit is not installed (install via
            ``pip install 'apcore-mcp[markdown]'``).
    """
    from apcore_toolkit import format_module

    scanned = descriptor_to_scanned_module(descriptor)
    rendered = format_module(scanned, style="markdown", display=display)
    if isinstance(rendered, str):
        return rendered
    # `format_module(style="json")` returns a dict; `markdown` returns
    # str. Defensive guard against future style additions.
    raise TypeError(f"format_module(style='markdown') returned {type(rendered).__name__}")
