"""The dashboard chart resolves its color tokens for the current theme and
re-plots when the theme changes. Plotly is served from the plotly package
instead of the CDN, so the test needs no network."""

from pathlib import Path

import plotly
import pytest
from playwright.sync_api import Page

from tests.web_support import PAGES

pytestmark = [pytest.mark.browser, pytest.mark.db]

PLOTLY_JS = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"


def colors(page: Page) -> list[str]:
    """Every trace's resolved color, as plotted."""
    return page.evaluate(
        """() => document.getElementById('net-worth-chart').data.map(
            t => t.type === 'bar' ? t.marker.color : t.line.color)"""
    )


def test_chart_rethemes_with_the_color_scheme(open_page, seeded):
    page = open_page("about:blank")
    page.route(
        "https://cdn.plot.ly/**",
        lambda route: route.fulfill(path=PLOTLY_JS, content_type="text/javascript"),
    )
    page.emulate_media(color_scheme="light")
    page.goto(f"{PAGES}?range=all")
    page.wait_for_function(
        "document.getElementById('net-worth-chart').data !== undefined"
    )
    light = colors(page)
    assert light and all(c.startswith("rgba(") for c in light), light
    font = page.evaluate("document.getElementById('net-worth-chart').layout.font.color")

    page.emulate_media(color_scheme="dark")
    page.wait_for_function(
        "([before]) => document.getElementById('net-worth-chart').layout.font.color !== before",
        arg=[font],
    )
    dark = colors(page)
    assert len(dark) == len(light) and dark != light

    page.emulate_media(color_scheme="light")
    page.wait_for_function(
        "([before]) => document.getElementById('net-worth-chart').layout.font.color === before",
        arg=[font],
    )
    assert colors(page) == light
