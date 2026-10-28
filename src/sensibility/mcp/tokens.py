"""identity's access tokens for /mcp: configuration and verification.

A token is accepted only if it is identity's RFC 9068 access token for this
resource: an ES256 JWT signed by a key in identity's JWKS, with header
`typ: at+jwt`, `iss` exactly identity's (external) issuer, `aud` holding
this server's MCP URL, and `exp`, `iat`, `sub` and `client_id` present.
Nothing else is accepted: not an ID token (no `typ`), not a token minted
for another app (another `aud`), not one from another issuer.

The JWKS is fetched from IDP_URL, identity's in-cluster address: pods cannot
resolve the external hostnames, so the issuer we compare against and the
URL we fetch keys from differ, as in the web login (`web/auth.py`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import jwt
from jwt import PyJWKClient

READ_SCOPE = "sensibility:read"
WRITE_SCOPE = "sensibility:write"
SCOPES = (READ_SCOPE, WRITE_SCOPE)
ALGORITHM = "ES256"
# RFC 9068 §4: "at+jwt", or the full media type; compared case-insensitively.
ACCESS_TOKEN_TYPES = {"at+jwt", "application/at+jwt"}
PRM_PREFIX = "/.well-known/oauth-protected-resource"


class InvalidToken(Exception):
    """The bearer token is not one this server accepts. The message is for
    logs; the client only learns that the token is invalid."""


@dataclass(frozen=True)
class McpConfig:
    resource: str  # the MCP URL, exactly as configured: the `aud` and PRM `resource`
    issuer: str  # identity's issuer, exactly as it appears in `iss`
    jwks_url: str  # identity's JWKS at its in-cluster address

    @property
    def metadata_url(self) -> str:
        """The protected resource metadata URL (RFC 9728 §3.1): the
        well-known prefix inserted between the host and the resource path."""
        parts = urlsplit(self.resource)
        path = PRM_PREFIX + parts.path.rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def mcp_config() -> McpConfig | None:
    """From MCP_RESOURCE_URL, IDP_ISSUER and IDP_URL; None if any is unset,
    in which case /mcp refuses every request (it fails closed)."""
    resource = os.environ.get("MCP_RESOURCE_URL", "").strip()
    issuer = os.environ.get("IDP_ISSUER", "").strip()
    idp_url = os.environ.get("IDP_URL", "").strip().rstrip("/")
    if not (resource and issuer and idp_url):
        return None
    return McpConfig(
        resource=resource,
        issuer=issuer,
        jwks_url=f"{idp_url}/.well-known/jwks.json",
    )


def canonical_url(url: str) -> str:
    """A URL for comparison: scheme and host lowercased, a default port
    dropped, and no trailing slash. `https://Sensibility.money:443/mcp/`
    and `https://sensibility.money/mcp` are the same resource."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    default = {"https": 443, "http": 80}.get(scheme)
    netloc = host if port is None or port == default else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), parts.query, ""))


class KeySource(Protocol):
    def key_for(self, token: str) -> Any:
        """The public key that should have signed `token`; raises
        InvalidToken if there is none."""
        ...


class JwksKeys:
    """identity's signing keys from its JWKS, cached by PyJWKClient (the
    set for five minutes; an unknown `kid` refetches it, at most every 30s)."""

    def __init__(self, url: str):
        self.client: PyJWKClient = PyJWKClient(url, cache_keys=True)

    def key_for(self, token: str) -> Any:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            if kid is not None:
                return self.client.get_signing_key_from_jwt(token).key
            # No kid: acceptable only while identity publishes one key.
            keys = self.client.get_signing_keys()
        except jwt.PyJWTError as e:
            raise InvalidToken(f"No signing key: {e}") from e
        if len(keys) != 1:
            raise InvalidToken("Token has no kid and the JWKS has several keys")
        return keys[0].key


@cache
def jwks_keys(url: str) -> KeySource:
    """One cached key source per JWKS URL, for the life of the process."""
    return JwksKeys(url)


def key_source(config: McpConfig) -> KeySource:
    """Where /mcp gets identity's keys. Tests replace this."""
    return jwks_keys(config.jwks_url)


def verify(token: str, config: McpConfig, keys: KeySource) -> dict[str, Any]:
    """The token's claims, if it is identity's access token for this resource.

    Raises InvalidToken otherwise.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise InvalidToken(f"Not a JWT: {e}") from e
    typ = header.get("typ")
    if not isinstance(typ, str) or typ.lower() not in ACCESS_TOKEN_TYPES:
        raise InvalidToken(f"typ is {typ!r}, not at+jwt")
    key = keys.key_for(token)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            issuer=config.issuer,
            options={
                "require": ["exp", "iat", "iss", "sub", "aud"],
                # Checked below, comparing canonical forms.
                "verify_aud": False,
            },
        )
    except jwt.PyJWTError as e:
        raise InvalidToken(str(e)) from e
    audiences = claims["aud"]
    if isinstance(audiences, str):
        audiences = [audiences]
    expected = canonical_url(config.resource)
    if not any(isinstance(a, str) and canonical_url(a) == expected for a in audiences):
        raise InvalidToken(f"aud {claims['aud']!r} is not {config.resource}")
    if not isinstance(claims["sub"], str) or not claims["sub"]:
        raise InvalidToken("sub is missing")
    if not isinstance(claims.get("client_id"), str):
        raise InvalidToken("client_id is missing")
    return claims


def scopes_of(claims: dict[str, Any]) -> frozenset[str]:
    """The token's space-separated `scope` claim as a set."""
    scope = claims.get("scope")
    return frozenset(scope.split()) if isinstance(scope, str) else frozenset()
