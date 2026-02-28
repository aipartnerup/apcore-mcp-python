"""Authentication support for apcore-mcp."""

from apcore_mcp.auth.jwt import ClaimMapping, JWTAuthenticator
from apcore_mcp.auth.middleware import AuthMiddleware, auth_identity_var, extract_headers
from apcore_mcp.auth.protocol import Authenticator

__all__ = [
    "Authenticator",
    "JWTAuthenticator",
    "ClaimMapping",
    "AuthMiddleware",
    "auth_identity_var",
    "extract_headers",
]
