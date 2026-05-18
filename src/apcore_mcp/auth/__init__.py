"""Authentication support for apcore-mcp."""

from __future__ import annotations

from apcore_mcp.auth.jwt import ClaimMapping, JWTAuthenticator
from apcore_mcp.auth.middleware import AuthMiddleware, auth_identity_var, extract_headers
from apcore_mcp.auth.protocol import Authenticator, Identity


def get_current_identity() -> Identity | None:
    """Return the authenticated identity for the active request, if any.

    Reads from the ``auth_identity_var`` ContextVar that ``AuthMiddleware``
    sets at the top of every authenticated ASGI request. Returns ``None``
    when the request bypassed auth (exempt path) or no middleware is
    installed. Cross-SDK parity with TypeScript ``getCurrentIdentity()``
    and Rust ``AUTH_IDENTITY.get()``.
    """
    return auth_identity_var.get()


__all__ = [
    "Authenticator",
    "JWTAuthenticator",
    "ClaimMapping",
    "AuthMiddleware",
    "auth_identity_var",
    "extract_headers",
    "get_current_identity",
]
