"""Helpers for MCP tests: a test signing key, tokens minted with it, callers."""

import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from sensibility.mcp.tokens import READ_SCOPE, WRITE_SCOPE
from sensibility.mcp.tools import Caller
from sensibility.models import User
from tests.support import SEED_USER

KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())
KID = "test-key"
RESOURCE = "https://sensibility.money/mcp"
ISSUER = "https://identity.example.com"
IDP_URL = "http://identity.identity-test.svc.cluster.local"
PRM_URL = "https://sensibility.money/.well-known/oauth-protected-resource/mcp"
BOTH = f"{READ_SCOPE} {WRITE_SCOPE}"
CLIENT_ID = "https://claude.ai/oauth/claude-code-client-metadata"


class StaticKeys:
    """identity's JWKS, in tests: always the test key's public half."""

    def key_for(self, token: str) -> Any:
        return KEY.public_key()


def claims_for(user: dict = SEED_USER, scope: str = BOTH, **overrides) -> dict:
    """What identity puts in an MCP access token for this user."""
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": [RESOURCE],
        "sub": user["sub"],
        "client_id": CLIENT_ID,
        "scope": scope,
        "email": user["email"],
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
        "jti": str(uuid.uuid4()),
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def mint(
    user: dict = SEED_USER,
    scope: str = BOTH,
    *,
    key=KEY,
    algorithm: str = "ES256",
    headers: dict | None = None,
    **overrides,
) -> str:
    """A token signed like identity's. Pass a claim as None to leave it out;
    `headers={"typ": None}` leaves out typ."""
    header = {"typ": "at+jwt", "kid": KID, **(headers or {})}
    header = {k: v for k, v in header.items() if v is not None}
    if "typ" not in header:
        header["typ"] = ""  # PyJWT drops a falsy typ; it would add "JWT"
    return jwt.encode(
        claims_for(user, scope, **overrides), key, algorithm=algorithm, headers=header
    )


def caller(user: dict = SEED_USER, scopes=(READ_SCOPE, WRITE_SCOPE)) -> Caller:
    return Caller(
        user=User(
            id=user["id"], idp_sub=user["sub"], email=user["email"], name=user["name"]
        ),
        scopes=frozenset(scopes),
        client_id=CLIENT_ID,
    )
