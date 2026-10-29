"""Every page the app serves, on a phone: where a new page gets noticed.

The pages are the React app's routes (frontend/src/router.tsx), listed in
frontend/src/page-routes.json, which a Vitest test keeps equal to the
router; the server's own HTML page is /login. test_every_page_is_swept fails
when either has a page with no entry in SCREENS, so adding a page means
deciding how it looks on a phone. test_the_screen_fits opens each one at
320px and 390px and runs assert_fits_phone over the whole page, header and
tab bar included; the refused logins (403) get the same. Each area's
test_spa_*.py covers the states that change its layout (confirms, errors,
staged edits, empty pages).
"""

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from sensibility.cashflows import create_cash_flow, create_category
from sensibility.models import CashFlow, CashFlowDirection, FrequencyUnit
from tests.browser.mobile import PHONE_WIDTHS, assert_fits_phone
from tests.support import WS
from tests.web_support import USER, FakeIdp, claims

pytestmark = [pytest.mark.browser, pytest.mark.db]

PAGE_ROUTES = Path(__file__).resolve().parents[2] / "frontend/src/page-routes.json"
W = "/workspaces/:workspaceId"
PAGE, DRAWER = "main h2", "[role=dialog]"

# Route (as the router or the OpenAPI schema names it) -> the page to open
# for it, and what shows once it has rendered (None: served whole).
SCREENS = {
    "/": ("/", PAGE),  # into your oldest workspace's dashboard
    "/accounts": ("/accounts", PAGE),  # into its Accounts
    "/welcome": ("/welcome", PAGE),
    W: ("/workspaces/{ws}", PAGE),
    f"{W}/accounts": ("/workspaces/{ws}/accounts", PAGE),
    f"{W}/accounts/new": ("/workspaces/{ws}/accounts/new", DRAWER),
    f"{W}/accounts/:accountId/edit": ("/workspaces/{ws}/accounts/{tax}/edit", DRAWER),
    f"{W}/cash-flows": ("/workspaces/{ws}/cash-flows", PAGE),
    f"{W}/cash-flows/new": ("/workspaces/{ws}/cash-flows/new", DRAWER),
    f"{W}/cash-flows/:flowId/edit": (
        "/workspaces/{ws}/cash-flows/{flow}/edit",
        DRAWER,
    ),
    f"{W}/cash-flow-categories": ("/workspaces/{ws}/cash-flow-categories", DRAWER),
    f"{W}/settings": ("/workspaces/{ws}/settings", PAGE),
    "/login": ("/login", None),
}
# A long name, so the refused page's email has to wrap.
LONG_NAME = {
    "id": 2,
    "sub": "user-2",
    "email": "alexandra.rivera-montgomery.the.third@example.com",
    "name": "Alexandra Rivera-Montgomery-Featherstonehaugh",
}


def spa_routes() -> set[str]:
    return set(json.loads(PAGE_ROUTES.read_text()))


def html_routes() -> set[str]:
    """The server's own pages: routes whose 200 is HTML."""
    from sensibility.web.app import app

    return {
        path
        for path, operations in app.openapi()["paths"].items()
        if "text/html"
        in operations.get("get", {})
        .get("responses", {})
        .get("200", {})
        .get("content", {})
    }


def test_every_page_is_swept(client):
    # client sets the environment the app needs to import.
    assert html_routes() == {"/login"}
    assert spa_routes() | html_routes() == set(SCREENS)


@pytest.fixture
def ids(db_connection, seeded) -> dict:
    """seeded's accounts (and their snapshot), plus a category and a flow."""
    category = create_category(db_connection, WS, "Housing")
    flow = create_cash_flow(
        db_connection,
        WS,
        CashFlow(
            name="Mortgage payment",
            direction=CashFlowDirection.EXPENSE,
            amount=Decimal("2650"),
            unit=FrequencyUnit.MONTH,
            category_id=category.id,
        ),
    )
    return {"ws": WS, "tax": seeded["tax"].id, "flow": flow.id}


def settle(page) -> None:
    """A drawer slides up on a phone; measure once it has arrived."""
    page.wait_for_function(
        "document.getAnimations().every(a => a.playState === 'finished')"
    )


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("route", sorted(SCREENS))
def test_the_screen_fits(open_page, ids, route, width):
    path, ready = SCREENS[route]
    page = open_page(path.format(**ids), phone=width)
    if ready:
        # The React app renders after its first API call.
        page.locator(ready).first.wait_for()
    settle(page)
    assert_fits_phone(page)


def _refused_login_html(client, monkeypatch, info: dict) -> str:
    """The real 403 page from the in-process app: the browser's server is a
    subprocess, so its identity provider cannot be faked there."""
    import sensibility.web.app as app_module

    monkeypatch.setattr(
        app_module,
        "get_oauth_client",
        lambda: SimpleNamespace(idp=FakeIdp(token={"userinfo": info})),
    )
    monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
    response = client.get("/auth/callback", follow_redirects=False)
    assert response.status_code == 403
    return response.text


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize(
    "info",
    [
        pytest.param(claims(LONG_NAME), id="not-allowed"),
        pytest.param(claims(USER, email_verified=False), id="unverified"),
    ],
)
def test_a_refused_login_fits(open_page, client, monkeypatch, width, info):
    html = _refused_login_html(client, monkeypatch, info)
    page = open_page("/login", phone=width)
    page.route(
        "**/auth/callback",
        lambda route: route.fulfill(status=403, content_type="text/html", body=html),
    )
    page.goto("/auth/callback")
    assert page.locator(".login-card.refused").count() == 1
    assert_fits_phone(page)
