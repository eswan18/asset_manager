"""Loading states of the React app (frontend/README.md, "Loading"), in a real
browser with responses held back by `page.route`: a click on an account
opens its drawer at once with its header, before the server answers, and
the rest lands after; a page's first load shows its skeleton in its own
layout; a drawer still loading fits a phone."""

import pytest
from playwright.sync_api import Page, Route, expect

from tests.browser.mobile import PHONE_WIDTHS, assert_fits_phone
from tests.browser.test_spa_accounts import ACCOUNTS
from tests.support import WS

pytestmark = [pytest.mark.browser, pytest.mark.db]

API = f"/api/workspaces/{WS}/accounts"


class Held:
    """Requests whose URL path ends with `path`: held until `release()`, then
    let through. `count` counts them all."""

    def __init__(self, page: Page, path: str):
        self.page = page
        self.routes: list[Route] = []
        self.count = 0
        self.released = False

        def handle(route: Route) -> None:
            self.count += 1
            if self.released:
                route.continue_()
            else:
                self.routes.append(route)

        page.route(lambda url: url.split("?")[0].endswith(path), handle)

    def wait(self) -> None:
        for _ in range(100):
            if self.routes:
                return
            self.page.wait_for_timeout(20)
        raise AssertionError("the request was never made")

    def release(self) -> None:
        self.released = True
        for route in self.routes:
            route.continue_()


def time_to_dialog(page: Page) -> None:
    """From now on, record when a click lands and when a dialog with a
    title appears (`window.__opened`, in ms after the click)."""
    page.evaluate(
        """() => {
        let clicked = null;
        document.addEventListener('click', () => { clicked = performance.now(); },
          {capture: true, once: true});
        new MutationObserver((_, observer) => {
          if (clicked !== null && document.querySelector('[role=dialog] h2')) {
            window.__opened = performance.now() - clicked;
            observer.disconnect();
          }
        }).observe(document.body, {childList: true, subtree: true});
    }"""
    )


def quiet(page: Page) -> None:
    """Every finite animation done (the drawer's slide, the skeleton's
    fade-in); a skeleton's pulse runs forever."""
    page.wait_for_function(
        "document.getAnimations().every(a => a.playState === 'finished'"
        " || a.effect.getTiming().iterations === Infinity)"
    )


def test_an_account_opens_before_its_detail_arrives(open_page, seeded):
    page = open_page(ACCOUNTS)
    checking = seeded["checking"]
    link = page.get_by_role("link", name="Checking", exact=True)
    expect(link).to_be_visible()
    detail = Held(page, f"{API}/{checking.id}")
    time_to_dialog(page)

    # The pointer on the way to the click starts the detail (prefetch).
    link.click()
    dialog = page.get_by_role("dialog", name="Checking")
    expect(dialog).to_be_visible()
    detail.wait()
    assert page.evaluate("window.__opened") < 100

    # The header and the form are there, from the page's overview, before
    # the server has answered; only the history and Retire wait.
    expect(dialog).to_contain_text("Edit asset")
    expect(dialog.get_by_label("Name")).to_be_focused()
    expect(dialog.get_by_label("Name")).to_have_value("Checking")
    busy = dialog.locator("[data-slot=loading][aria-busy=true]")
    expect(busy).to_have_count(1)
    expect(dialog.get_by_role("region", name="Retire")).to_have_count(0)

    dialog.get_by_label("Name").press("End")
    dialog.get_by_label("Name").press_sequentially(" account")
    detail.release()
    expect(dialog.get_by_role("region", name="Retire")).to_be_visible()
    expect(busy).to_have_count(0)
    # The detail landing kept what was typed, and was asked for once.
    expect(dialog.get_by_label("Name")).to_have_value("Checking account")
    assert detail.count == 1


def test_an_account_by_its_url_shows_the_form_after_the_overview(open_page, seeded):
    page = open_page(ACCOUNTS)
    expect(page.get_by_role("heading", name="Accounts")).to_be_visible()
    tax = seeded["tax"]
    overview = Held(page, f"{API}/overview")
    detail = Held(page, f"{API}/{tax.id}")
    page.goto(f"{ACCOUNTS}/{tax.id}/edit")

    # The sheet is up and busy, its title a skeleton, before any answer.
    dialog = page.get_by_role("dialog", name="Loading account")
    expect(dialog).to_be_visible()
    expect(dialog).to_have_attribute("aria-busy", "true")
    overview.wait()
    detail.wait()
    expect(dialog.locator("[data-slot=skeleton]").first).to_be_visible()

    # The overview is enough for the form; the detail follows.
    overview.release()
    form = page.get_by_role("dialog", name="Cap gains tax")
    expect(form.get_by_label("Name")).to_be_focused()
    expect(form.get_by_role("region", name="Retire")).to_have_count(0)
    detail.release()
    expect(form.get_by_role("region", name="Retire")).to_be_visible()
    expect(form.get_by_label("Name")).to_be_focused()
    expect(form).not_to_have_attribute("aria-busy", "true")
    # Escape still closes it.
    page.keyboard.press("Escape")
    page.wait_for_url(f"**{ACCOUNTS}")


def test_a_page_first_load_shows_its_skeleton(open_page, seeded):
    page = open_page(ACCOUNTS)
    expect(page.get_by_role("heading", name="Accounts")).to_be_visible()
    overview = Held(page, f"{API}/overview")
    page.reload()

    skeleton = page.locator("main [data-slot=loading][aria-busy=true]")
    expect(skeleton).to_be_visible()
    overview.wait()
    # The page's own layout: the two cards, with rows and amount fields.
    expect(skeleton.locator("[data-slot=card]")).to_have_count(2)
    # It fades in only after 150ms, so a quick answer never flashes it.
    page.wait_for_function(
        "getComputedStyle(document.querySelector("
        "'main [data-slot=loading]')).opacity === '1'"
    )
    expect(page.get_by_role("heading", name="Accounts")).to_have_count(0)

    overview.release()
    expect(page.get_by_role("heading", name="Accounts")).to_be_visible()
    expect(skeleton).to_have_count(0)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_loading_drawer_fits_a_phone(open_page, seeded, width):
    page = open_page(ACCOUNTS, phone=width)
    expect(page.get_by_role("heading", name="Accounts")).to_be_visible()
    checking = seeded["checking"]
    overview = Held(page, f"{API}/overview")
    detail = Held(page, f"{API}/{checking.id}")
    page.goto(f"{ACCOUNTS}/{checking.id}/edit")
    dialog = page.get_by_role("dialog", name="Loading account")
    expect(dialog).to_be_visible()
    overview.wait()
    detail.wait()
    quiet(page)
    assert_fits_phone(page)
    # A full-screen sheet, even before its content.
    box = dialog.bounding_box()
    assert box and box["width"] == width
    overview.release()
    detail.release()
    expect(page.get_by_role("dialog", name="Checking")).to_be_visible()
