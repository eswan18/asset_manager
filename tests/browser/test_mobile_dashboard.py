"""The dashboard on a phone (docs/superpowers/specs/2026-10-26-mobile-design.md):
it fits at 320 and 390, the chart is lines only at full width with the
category columns moved into two stacked bars under it, and it goes back to
the desktop figure when the screen widens. Plotly is served from the plotly
package, so no network is needed."""

import pytest
from playwright.sync_api import Page

from sensibility.accounts import create_account
from sensibility.models import RecordType
from tests.browser.mobile import PHONE_WIDTHS, assert_fits_phone
from tests.browser.test_dashboard_chart import PLOTLY_JS
from tests.support import WS
from tests.web_support import PAGES

pytestmark = [pytest.mark.browser, pytest.mark.db]


def open_dashboard(open_page, width: int | None, path: str = PAGES) -> Page:
    page = open_page("about:blank", phone=width)
    page.route(
        "https://cdn.plot.ly/**",
        lambda route: route.fulfill(path=PLOTLY_JS, content_type="text/javascript"),
    )
    page.goto(path)
    return page


def wait_for_chart(page: Page) -> None:
    page.wait_for_function(
        "document.getElementById('net-worth-chart').data !== undefined"
    )


def chart(page: Page) -> dict:
    """What is plotted: visible bar traces, the line axis's domain, the
    figure's height and whether it drags."""
    return page.evaluate(
        """() => {
        const el = document.getElementById('net-worth-chart');
        const bars = el.data.filter(t => t.type === 'bar' && t.visible !== false);
        const plot = el.querySelector('.nsewdrag[data-subplot=xy]');
        return {
            bars: bars.length,
            domain: el._fullLayout.xaxis.domain,
            height: el._fullLayout.height,
            dragmode: el._fullLayout.dragmode,
            plotWidth: plot ? plot.getBoundingClientRect().width : 0,
            chartWidth: el.getBoundingClientRect().width,
            shapes: el._fullLayout.shapes.length,
            columnsSubplot: el.querySelector('.nsewdrag[data-subplot=x2y]') !== null,
        };
    }"""
    )


def bars_shown(page: Page) -> bool:
    return page.locator(".category-bars .category-bar").first.is_visible()


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_dashboard_fits_a_phone(open_page, seeded, width):
    page = open_dashboard(open_page, width)
    wait_for_chart(page)
    assert_fits_phone(page)
    # Update balances spans the card; the range toggle's segments are 44px.
    button = page.get_by_role("link", name="Update balances").bounding_box()
    card = page.locator(".overview .headline").bounding_box()
    assert button and card and abs(button["width"] - card["width"]) < 1
    for box in page.locator(".chart-controls .toggle a").all():
        assert (box.bounding_box() or {})["height"] >= 44


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_viewer_dashboard_fits_a_phone(open_page, seeded, db_connection, width):
    db_connection.execute("UPDATE workspace_members SET role = 'viewer'")
    db_connection.commit()
    page = open_dashboard(open_page, width)
    wait_for_chart(page)
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("with_accounts", [False, True])
def test_the_getting_started_dashboard_fits_a_phone(
    open_page, db_connection, width, with_accounts
):
    if with_accounts:
        create_account(db_connection, WS, "Checking", RecordType.ASSET)
    page = open_dashboard(open_page, width)
    page.get_by_role("heading", name="Let's get your first net worth").wait_for()
    assert_fits_phone(page)
    welcome = page.locator(".welcome").bounding_box()
    placeholder = page.locator(".placeholder-chart").bounding_box()
    assert welcome and placeholder
    assert placeholder["x"] + placeholder["width"] <= welcome["x"] + welcome["width"]


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_phone_chart_is_lines_only_at_full_width_with_bars_below(
    open_page, seeded, width
):
    page = open_dashboard(open_page, width)
    wait_for_chart(page)
    plotted = chart(page)
    assert plotted["bars"] == 0
    # Not merely hidden: an empty columns subplot would still catch taps.
    assert not plotted["columnsSubplot"]
    assert plotted["shapes"] == 0  # no divider before columns that are gone
    assert plotted["domain"] == [0, 1]
    assert plotted["height"] == 240
    # The lines' plot takes the chart's width, less the dollar labels.
    assert plotted["plotWidth"] > plotted["chartWidth"] - 70
    assert bars_shown(page)
    # One bar per type, each above its own key, in the columns' colors.
    titles = page.locator(".category-bar .bar-title").all_inner_texts()
    assert titles == ["Assets", "Liabilities"]
    asset_bar = page.locator(".category-bar.kind-asset").bounding_box()
    asset_key = page.locator(".key-group.kind-asset").bounding_box()
    liability_bar = page.locator(".category-bar.kind-liability").bounding_box()
    assert asset_bar and asset_key and liability_bar
    assert asset_bar["y"] < asset_key["y"] < liability_bar["y"]
    colors = page.locator(".bar-segment").evaluate_all(
        "els => els.map(e => getComputedStyle(e).backgroundColor)"
    )
    swatches = page.locator(".category-key .category-swatch").evaluate_all(
        "els => els.map(e => getComputedStyle(e).backgroundColor)"
    )
    assert colors == swatches


def test_the_phone_chart_does_not_drag_and_a_tap_shows_the_values(open_page, seeded):
    page = open_dashboard(open_page, 390)
    wait_for_chart(page)
    assert chart(page)["dragmode"] is False
    # seeded has one snapshot, plotted at the right edge of the lines.
    plot = page.locator("#net-worth-chart .nsewdrag[data-subplot=xy]")
    box = plot.bounding_box()
    assert box
    # Record every label the hover layer shows: a later synthetic mouse
    # event may clear it again before the test could look.
    page.evaluate(
        """() => {
        window.hoverTexts = [];
        const layer = document.querySelector('#net-worth-chart .hoverlayer');
        new MutationObserver(() => {
            if (layer.textContent) window.hoverTexts.push(layer.textContent);
        }).observe(layer, { childList: true, subtree: true, characterData: true });
    }"""
    )
    # Right on the snapshot's date, wherever the axis puts it.
    x = page.evaluate(
        """() => {
        const el = document.getElementById('net-worth-chart');
        const ax = el._fullLayout.xaxis;
        return ax.l2p(ax.d2l(el.data[0].x[0]));
    }"""
    )
    plot.tap(position={"x": x, "y": box["height"] / 2})
    shown = page.wait_for_function(
        "window.hoverTexts.find(t => t.includes('Net worth'))"
    ).json_value()
    assert "Assets" in shown and "Liabilities" in shown and "$" in shown


def test_the_chart_relays_when_the_width_crosses_the_breakpoint(open_page, seeded):
    page = open_dashboard(open_page, 390)
    wait_for_chart(page)
    assert chart(page)["bars"] == 0

    page.set_viewport_size({"width": 1280, "height": 900})
    page.wait_for_function(
        """() => document.getElementById('net-worth-chart').data
            .some(t => t.type === 'bar' && t.visible !== false)"""
    )
    plotted = chart(page)
    assert plotted["bars"] == 2  # one category (Uncategorized) per column
    assert plotted["domain"][1] < 1 and plotted["shapes"] == 1
    assert plotted["columnsSubplot"]
    assert plotted["height"] == 320
    assert not bars_shown(page)

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_function(
        """() => !document.getElementById('net-worth-chart').data
            .some(t => t.type === 'bar' && t.visible !== false)"""
    )
    assert bars_shown(page)


def test_a_desktop_dashboard_has_columns_and_no_bars(open_page, seeded):
    page = open_dashboard(open_page, None)
    wait_for_chart(page)
    plotted = chart(page)
    assert plotted["bars"] == 2 and plotted["height"] == 320
    assert not bars_shown(page)
