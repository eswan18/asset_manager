"""Serving the React app from the root (web/spa.py), against a stand-in build."""

import re
from importlib import resources
from pathlib import Path

import pytest

from sensibility.web.spa import IMMUTABLE, NO_CACHE
from tests.web_support import PUBLIC_PATHS

pytestmark = pytest.mark.db

INDEX = '<!doctype html><div id="root"></div><script src="/assets/index-abc123.js"></script>'
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def dist(tmp_path, monkeypatch) -> Path:
    """A minimal build, as `npm run build` lays it out."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log('app')")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    monkeypatch.setenv("SPA_DIST", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/welcome",
        "/welcome?x=1",
        "/accounts",
        "/workspaces/1",
        "/workspaces/1?range=6m",
        "/workspaces/1/accounts/4/edit",
        "/workspaces/1/cash-flows?per=year",
        "/workspaces/1/settings",
        "/no/such/page",
    ],
)
def test_every_app_path_gets_index_uncached(client, dist, path):
    """Logged out, too: the shell holds no data."""
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == NO_CACHE


@pytest.mark.parametrize(
    "path, target",
    [
        ("/app", "/"),
        ("/app/", "/"),
        ("/app/workspaces/1", "/workspaces/1"),
        ("/app/x?y=1", "/x?y=1"),
        ("/app/workspaces/1?range=6m", "/workspaces/1?range=6m"),
        (
            "/app/workspaces/1/cash-flows/new?per=year&x=a%20b",
            "/workspaces/1/cash-flows/new?per=year&x=a%20b",
        ),
    ],
)
def test_the_old_app_prefix_redirects_permanently(client, dist, path, target):
    """Bookmarks from the build-out, when the app lived under /app."""
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == target


def test_a_path_that_only_starts_like_app_is_the_app(client, dist):
    response = client.get("/apple", follow_redirects=False)
    assert response.status_code == 200
    assert response.text == INDEX


def test_hashed_assets_are_cached_for_a_year(client, dist):
    response = client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.text == "console.log('app')"
    assert response.headers["cache-control"] == IMMUTABLE
    assert "javascript" in response.headers["content-type"]


def test_head_answers_like_get(client, dist):
    for path, status in (("/assets/index-abc123.js", 200), ("/workspaces/1", 200)):
        response = client.head(path)
        assert response.status_code == status, path
        assert response.text == ""
    assert client.head("/assets/gone-123.js").status_code == 404


def test_a_missing_asset_is_a_404_not_the_app(client, dist):
    response = client.get("/assets/gone-123.js")
    assert response.status_code == 404
    assert INDEX not in response.text


def test_other_built_files_are_served(client, dist):
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.text == "<svg/>"
    assert response.headers["cache-control"] == NO_CACHE


@pytest.mark.parametrize(
    "path",
    [
        "/assets/../../secret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/%2e%2e/secret.txt",
    ],
)
def test_nothing_outside_the_build_is_served(client, dist, path):
    (dist.parent / "secret.txt").write_text("secret")
    response = client.get(path)
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/no-such-thing",
        "/api/workspaces/1/no-such-thing",
        "/auth/no-such-thing",
        "/.well-known/no-such-thing",
    ],
)
def test_unknown_server_paths_stay_json_404s(client, dist, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert INDEX not in response.text


def test_the_api_still_answers(client, dist):
    """Logged out: the API's own 401, not the app."""
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.json() == {"error": "Login required"}


def test_login_is_the_servers_page(client, dist, monkeypatch):
    def unreachable():
        raise RuntimeError("identity is down")

    monkeypatch.setattr("sensibility.web.app.get_oauth_client", unreachable)
    response = client.get("/login")
    assert response.status_code == 200
    assert "Log in" in response.text
    assert INDEX not in response.text


@pytest.mark.parametrize(
    "path, status",
    [("/health", 200), ("/openapi.json", 200), ("/docs", 200), ("/redoc", 200)],
)
def test_server_paths_keep_winning(client, dist, path, status):
    response = client.get(path)
    assert response.status_code == status
    assert INDEX not in response.text


def test_mcp_reaches_the_server(client, dist, mcp_env):
    """Without a token: the gate's 401, not the app."""
    response = client.post("/mcp", json={})
    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]
    assert client.get("/mcp").status_code == 401


def test_the_protected_resource_metadata_reaches_the_server(client, dist, mcp_env):
    response = client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert "resource" in response.json()


def test_logout_and_auth_reach_the_server(client, dist, monkeypatch):
    """No identity: both clear the session and go to /login."""

    def unreachable():
        raise RuntimeError("identity is down")

    monkeypatch.setattr("sensibility.web.app.get_oauth_client", unreachable)
    for path in ("/logout", "/auth/switch"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"


def test_the_app_is_not_in_the_api_schema(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not [
        p
        for p in paths
        if not p.startswith(("/api/", "/.well-known/")) and p not in PUBLIC_PATHS
    ]


def test_without_a_build_the_app_explains_with_a_503(client, tmp_path, monkeypatch):
    monkeypatch.setenv("SPA_DIST", str(tmp_path / "missing"))
    response = client.get("/workspaces/1")
    assert response.status_code == 503
    assert "npm run build" in response.text


def test_the_default_build_is_the_checkouts(monkeypatch):
    from sensibility.web.spa import dist_dir

    monkeypatch.delenv("SPA_DIST", raising=False)
    assert dist_dir() == REPO / "frontend" / "dist"


def _tokens(css: str) -> dict[str, dict[str, str]]:
    """{"light": {name: value}, "dark": {...}} from :root blocks."""
    dark_start = css.find("@media (prefers-color-scheme: dark)")
    found = {}
    for theme, text in (("light", css[:dark_start]), ("dark", css[dark_start:])):
        block = text[text.find(":root") :]
        block = block[: block.find("}")]
        found[theme] = {
            name: re.sub(r"\s+", " ", value.strip().lower())
            for name, value in re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", block)
        }
    return found


def test_the_spa_tokens_match_base_html():
    """login.html (base.html) and the React app define the same colors in
    both themes."""
    base = (
        resources.files("sensibility.web").joinpath("templates/base.html").read_text()
    )
    spa = (REPO / "frontend/src/styles/tokens.css").read_text()
    theirs, ours = _tokens(base), _tokens(spa)
    for theme in ("light", "dark"):
        colors = {
            k: v
            for k, v in theirs[theme].items()
            if not k.startswith(("--font", "--radius", "--gutter", "--tabbar"))
        }
        assert len(colors) >= 25
        assert {k: ours[theme].get(k) for k in colors} == colors, theme
    theme_css = (REPO / "frontend/src/index.css").read_text()
    for name in ("--radius-card: 20px", "--radius-input: 10px"):
        assert name in theme_css
