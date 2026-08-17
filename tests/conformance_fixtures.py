"""Locating the shared cross-language conformance fixtures.

The fixtures live in the apcore-mcp spec repository rather than here, because
all three bridges have to drive the same bytes for the comparison to mean
anything. This module is the single place that knows how to find them, and —
more importantly — the single place that decides what a *missing* fixture
means.

Every conformance module used to answer that question with a module-level
skip. That is the right answer for a contributor who has not checked the spec
repo out. It was the wrong answer in CI, where no workflow checked the spec
repo out at all: the suite reported success while 23 cross-language assertions
never ran, and nothing in the output distinguished that from having run them.
The answer therefore depends on where we are — skip locally, fail in CI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_FIXTURE_SUBPATH = Path("apcore-mcp") / "conformance" / "fixtures"
_ENV_OVERRIDE = "APCORE_CONFORMANCE_FIXTURES"
_MAX_ASCENT = 4


def fixtures_dir() -> Path | None:
    """Return the shared fixtures directory, or ``None`` when it is not present.

    Resolution order:

    1. ``APCORE_CONFORMANCE_FIXTURES`` — an explicit directory, for layouts
       neither convention below covers.
    2. Walking up from this file, looking for ``apcore-mcp/conformance/
       fixtures``. One walk covers both layouts: the sibling checkout
       developers use (``…/aipartnerup/apcore-mcp``) and CI, where the spec
       repo is checked out *inside* the workspace (``$GITHUB_WORKSPACE/
       apcore-mcp``) because ``actions/checkout`` refuses to place a
       repository outside it.
    """
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        candidate = Path(override)
        return candidate if candidate.is_dir() else None

    here = Path(__file__).resolve().parent
    for directory in [here, *here.parents][: _MAX_ASCENT + 1]:
        candidate = directory / _FIXTURE_SUBPATH
        if candidate.is_dir():
            return candidate
    return None


def load_fixture(name: str) -> dict:
    """Load a conformance fixture by file name.

    Skips the calling module when the fixtures are simply absent locally, and
    raises in CI, where absence means the suite is proving nothing.
    """
    directory = fixtures_dir()
    if directory is not None:
        path = directory / name
        if path.is_file():
            with path.open() as fh:
                return json.load(fh)

    detail = (
        f"conformance fixture {name!r} not found: checked ${_ENV_OVERRIDE} and "
        f"every ancestor of {Path(__file__).resolve().parent} for {_FIXTURE_SUBPATH}"
    )
    if os.environ.get("CI"):
        raise RuntimeError(
            f"{detail}. In CI this is a failure rather than a skip: the "
            "cross-language conformance suite exists to catch divergence "
            "between the three bridges, and skipping it silently reports "
            "success while proving nothing. The workflow must check out "
            "aiperceivable/apcore-mcp to the `apcore-mcp` path."
        )
    pytest.skip(
        f"{detail}. Check out aiperceivable/apcore-mcp alongside this repository to run it.",
        allow_module_level=True,
    )
