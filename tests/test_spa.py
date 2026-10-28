"""Serving the React app under /app (web/spa.py), against a stand-in build."""

import re
from importlib import resources
from pathlib import Path

import pytest

from sensibility.web.spa import IMMUTABLE, NO_CACHE

pytestmark = pytest.mark.db

INDEX = '<!doctype html><div id="root"></div><script src="/app/assets/index-abc123.js"></script>'
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
        "/app",
        "/app/",
        "/app/workspaces/1",
        "/app/workspaces/1/accounts/4/edit",
        "/app/welcome?x=1",
        "/app/no/such/page",
    ],
)
def test_every_app_path_gets_index_uncached(client, dist, path):
    """Logged out, too: the shell holds no data."""
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == NO_CACHE


def test_hashed_assets_are_cached_for_a_year(client, dist):
    response = client.get("/app/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.text == "console.log('app')"
    assert response.headers["cache-control"] == IMMUTABLE
    assert "javascript" in response.headers["content-type"]


def test_a_missing_asset_is_a_404_not_the_app(client, dist):
    response = client.get("/app/assets/gone-123.js")
    assert response.status_code == 404
    assert INDEX not in response.text


def test_other_built_files_are_served(client, dist):
    response = client.get("/app/favicon.svg")
    assert response.status_code == 200
    assert response.text == "<svg/>"


@pytest.mark.parametrize(
    "path", ["/app/assets/../../secret.txt", "/app/assets/%2e%2e/%2e%2e/secret.txt"]
)
def test_nothing_outside_the_build_is_served(client, dist, path):
    (dist.parent / "secret.txt").write_text("secret")
    response = client.get(path)
    assert "secret" not in response.text


def test_unknown_api_paths_stay_json_404s(client, dist):
    response = client.get("/api/no-such-thing")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert INDEX not in response.text


def test_without_a_build_app_explains_with_a_503(client, tmp_path, monkeypatch):
    monkeypatch.setenv("SPA_DIST", str(tmp_path / "missing"))
    response = client.get("/app/workspaces/1")
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
    """Until the Jinja pages go, both define the same colors in both themes."""
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
