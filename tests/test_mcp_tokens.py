"""Verifying identity's access tokens for /mcp (no database)."""

import time

import jwt
import pytest
from jwt import PyJWKClient
from jwt.algorithms import ECAlgorithm

from sensibility.mcp.tokens import (
    InvalidToken,
    JwksKeys,
    McpConfig,
    canonical_url,
    mcp_config,
    scopes_of,
    verify,
)
from tests.mcp_support import (
    IDP_URL,
    ISSUER,
    KEY,
    KID,
    OTHER_KEY,
    PRM_URL,
    RESOURCE,
    StaticKeys,
    mint,
)

CONFIG = McpConfig(
    resource=RESOURCE, issuer=ISSUER, jwks_url=f"{IDP_URL}/.well-known/jwks.json"
)


def check(token: str) -> dict:
    return verify(token, CONFIG, StaticKeys())


def test_valid_token():
    claims = check(mint())
    assert claims["sub"] == "user-1"
    assert scopes_of(claims) == {"sensibility:read", "sensibility:write"}


@pytest.mark.parametrize("typ", ["at+jwt", "AT+JWT", "application/at+jwt"])
def test_typ_spellings(typ):
    assert check(mint(headers={"typ": typ}))["sub"] == "user-1"


@pytest.mark.parametrize(
    "token, reason",
    [
        (mint(key=OTHER_KEY), "Signature verification failed"),
        (mint(iss="https://evil.example.com"), "issuer"),
        # The issuer is compared exactly, as identity writes it.
        (mint(iss=ISSUER + "/"), "issuer"),
        (mint(aud=None), "aud"),
        (mint(aud=["https://sensibility.money/api"]), "aud"),
        (mint(aud=["https://staging.sensibility.money/mcp"]), "aud"),
        (mint(aud=[ISSUER]), "aud"),
        (mint(headers={"typ": None}), "typ"),
        # An ID token: typ JWT, and aud a client id.
        (mint(headers={"typ": "JWT"}, aud="sensibility-client"), "typ"),
        (mint(exp=int(time.time()) - 5), "expired"),
        (mint(exp=None), "exp"),
        (mint(iat=None), "iat"),
        (mint(sub=None), "sub"),
        (mint(client_id=None), "client_id"),
    ],
    ids=[
        "wrong-signature",
        "wrong-iss",
        "iss-trailing-slash",
        "no-aud",
        "aud-another-resource",
        "aud-staging",
        "aud-issuer",
        "no-typ",
        "id-token",
        "expired",
        "no-exp",
        "no-iat",
        "no-sub",
        "no-client-id",
    ],
)
def test_refused(token, reason):
    with pytest.raises(InvalidToken, match=reason):
        check(token)


def test_other_algorithms_are_refused():
    claims = {"sub": "user-1", "iss": ISSUER, "aud": [RESOURCE], "client_id": "x"}
    hs = jwt.encode(claims, "secret" * 6, algorithm="HS256", headers={"typ": "at+jwt"})
    with pytest.raises(InvalidToken):
        check(hs)
    unsigned = jwt.encode(claims, None, algorithm="none", headers={"typ": "at+jwt"})
    with pytest.raises(InvalidToken):
        check(unsigned)


def test_not_a_jwt():
    with pytest.raises(InvalidToken, match="Not a JWT"):
        check("not-a-token")


@pytest.mark.parametrize(
    "aud",
    [
        "https://sensibility.money/mcp",  # a plain string, not a list
        ["https://other.example.com/x", "https://sensibility.money/mcp"],
        ["https://Sensibility.Money/mcp/"],
        ["HTTPS://sensibility.money:443/mcp"],
    ],
)
def test_audience_compares_canonical_forms(aud):
    assert check(mint(aud=aud))["sub"] == "user-1"


def test_audience_path_is_case_sensitive():
    with pytest.raises(InvalidToken, match="aud"):
        check(mint(aud=["https://sensibility.money/MCP"]))


def test_canonical_url():
    assert canonical_url("HTTPS://Example.COM:443/mcp/") == "https://example.com/mcp"
    assert canonical_url("http://example.com:8080/mcp") == "http://example.com:8080/mcp"
    assert canonical_url("https://example.com") == "https://example.com"


def test_config_from_environment(monkeypatch):
    monkeypatch.setenv("MCP_RESOURCE_URL", RESOURCE)
    monkeypatch.setenv("IDP_ISSUER", ISSUER)
    monkeypatch.setenv("IDP_URL", IDP_URL + "/")
    config = mcp_config()
    assert config == CONFIG
    assert config is not None and config.metadata_url == PRM_URL


@pytest.mark.parametrize("missing", ["MCP_RESOURCE_URL", "IDP_ISSUER", "IDP_URL"])
def test_config_fails_closed(monkeypatch, missing):
    monkeypatch.setenv("MCP_RESOURCE_URL", RESOURCE)
    monkeypatch.setenv("IDP_ISSUER", ISSUER)
    monkeypatch.setenv("IDP_URL", IDP_URL)
    monkeypatch.delenv(missing)
    assert mcp_config() is None


def test_staging_metadata_url():
    config = McpConfig(
        resource="https://staging.sensibility.money/mcp", issuer=ISSUER, jwks_url=""
    )
    assert (
        config.metadata_url
        == "https://staging.sensibility.money/.well-known/oauth-protected-resource/mcp"
    )


class TestJwksKeys:
    """The real key source, with identity's JWKS endpoint stubbed."""

    @pytest.fixture
    def jwks(self, monkeypatch):
        keys = []
        fetched = []

        def publish(key, kid):
            jwk = ECAlgorithm.to_jwk(key.public_key(), as_dict=True)
            keys.append({**jwk, "kid": kid, "use": "sig", "alg": "ES256"})

        def fetch_data(self):
            fetched.append(self.uri)
            return {"keys": list(keys)}

        monkeypatch.setattr(PyJWKClient, "fetch_data", fetch_data)
        return publish, fetched

    def test_finds_the_key_by_kid(self, jwks):
        publish, fetched = jwks
        publish(OTHER_KEY, "old")
        publish(KEY, KID)
        source = JwksKeys(CONFIG.jwks_url)
        assert verify(mint(), CONFIG, source)["sub"] == "user-1"
        # Fetched from identity's in-cluster address, once, then cached.
        verify(mint(), CONFIG, source)
        assert fetched == [CONFIG.jwks_url]

    def test_unknown_kid_is_refused(self, jwks):
        publish, _ = jwks
        publish(KEY, KID)
        with pytest.raises(InvalidToken, match="No signing key"):
            verify(mint(headers={"kid": "rotated"}), CONFIG, JwksKeys(CONFIG.jwks_url))

    def test_no_kid_uses_the_only_key(self, jwks):
        publish, _ = jwks
        publish(KEY, KID)
        token = mint(headers={"kid": None})
        assert verify(token, CONFIG, JwksKeys(CONFIG.jwks_url))["sub"] == "user-1"

    def test_no_kid_with_several_keys_is_refused(self, jwks):
        publish, _ = jwks
        publish(KEY, KID)
        publish(OTHER_KEY, "other")
        with pytest.raises(InvalidToken, match="several keys"):
            verify(mint(headers={"kid": None}), CONFIG, JwksKeys(CONFIG.jwks_url))
