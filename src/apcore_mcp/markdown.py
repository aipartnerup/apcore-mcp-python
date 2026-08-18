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

import functools
import logging
from dataclasses import fields, is_dataclass
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "is_available",
    "render_module_markdown",
    "descriptor_to_scanned_module",
]


@functools.lru_cache(maxsize=1)
def is_available() -> bool:
    """Return True when apcore-toolkit is installed and its renderer is usable.

    [A-D-MD-5] The result is cached after the first resolution — this runs on
    every descriptor conversion, and re-running ``find_spec`` per call is pure
    overhead. Probing ``format_module`` rather than the bare package spec also
    means a broken or partial install reports False instead of True, matching
    the callable check in markdown.ts:46.
    """
    try:
        from apcore_toolkit import format_module
    except ImportError:
        return False
    return callable(format_module)


def descriptor_to_scanned_module(descriptor: Any) -> Any:
    """Adapt an apcore :class:`ModuleDescriptor` to a toolkit ``ScannedModule``.

    The two types are near-supersets of each other — this helper copies
    the overlapping fields and supplies sensible defaults (empty
    ``target``, no ``documentation``) for the toolkit-only ones.

    Raises ``ImportError`` when apcore-toolkit is not installed. Callers that
    need the never-raises contract should go through
    :func:`render_module_markdown`.
    """
    from apcore_toolkit import ScannedModule

    # [A-D-MD-8] The TypeScript and Rust adapters hardcode an empty target
    # because their descriptors carry none. Python has a real one and keeps it:
    # `target` takes no part in `format_module(style="markdown")`, so the
    # rendered bytes stay identical across SDKs while this public helper still
    # returns a faithful ScannedModule.
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
        # [A-D-MD-8] Both fields are set by the TypeScript adapter
        # (markdown.ts:107, :111) and the Rust one (markdown.rs:40, :50). Without
        # them, a toolkit whose ScannedModule declares `warnings` with no default
        # raises TypeError from the constructor below.
        "suggested_alias": None,
        "warnings": [],
    }
    if is_dataclass(ScannedModule):
        accepted = {f.name for f in fields(ScannedModule)}
        candidate_kwargs = {k: v for k, v in candidate_kwargs.items() if k in accepted}
    return ScannedModule(**candidate_kwargs)


def render_module_markdown(descriptor: Any, *, display: bool = True) -> str | None:
    """Render a :class:`ModuleDescriptor` as canonical apcore-toolkit markdown.

    Returns the markdown body produced by
    ``apcore_toolkit.format_module(scanned, style="markdown")`` — title,
    description, tags, behavior table (only fields differing from
    defaults — toolkit 0.6.0 alignment), JSON Schema for input/output,
    and examples.

    Args:
        descriptor: An apcore ``ModuleDescriptor`` (duck-typed).
        display: Honour the ``display`` overlay when present (default True).

    Returns:
        The rendered markdown, or ``None`` when apcore-toolkit is unavailable
        (install via ``pip install 'apcore-mcp[markdown]'``) or the toolkit
        could not produce a string. [A-D-MD-3] This never raises, so the
        spec-sanctioned ``render_module_markdown(d) or d.description`` works.
        TypeScript returns ``string | null`` (markdown.ts:136).
    """
    try:
        from apcore_toolkit import format_module
    except ImportError:
        logger.warning(
            "apcore-toolkit is not installed; install 'apcore-mcp[markdown]' to "
            "render Markdown module descriptions"
        )
        return None

    try:
        scanned = descriptor_to_scanned_module(descriptor)
        rendered = format_module(scanned, style="markdown", display=display)
    except Exception:
        logger.warning("format_module failed for %s", getattr(descriptor, "module_id", "?"), exc_info=True)
        return None

    if isinstance(rendered, str):
        return rendered
    # `format_module(style="json")` returns a dict; `markdown` returns
    # str. Defensive guard against future style additions.
    logger.warning("format_module(style='markdown') returned %s", type(rendered).__name__)
    return None
