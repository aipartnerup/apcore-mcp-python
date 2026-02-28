"""Authenticator protocol for pluggable authentication backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from apcore import Identity


@runtime_checkable
class Authenticator(Protocol):
    """Protocol for authentication backends.

    Implementations extract credentials from HTTP headers and return
    an ``Identity`` on success, or ``None`` on failure.
    """

    def authenticate(self, headers: dict[str, str]) -> Identity | None:
        """Authenticate a request from its headers.

        Args:
            headers: Lowercase header keys mapped to their values.

        Returns:
            An ``Identity`` if authentication succeeds, ``None`` otherwise.
        """
        ...
