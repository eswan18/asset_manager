"""Every page the app serves, on a phone: where a new page gets noticed.

test_every_page_is_swept fails when a route that returns HTML has no entry in
SCREENS, so adding a page means deciding how it looks on a phone.
test_the_screen_fits opens each one at 320px and 390px and runs
assert_fits_phone over the whole page, header and tab bar included. The
test_mobile_*.py file for each area covers the states that change its layout
(confirms, errors, staged edits, empty pages).
"""

from decimal import Decimal

import pytest

from sensibility.cashflows import create_cash_flow, create_category
from sensibility.models import CashFlow, CashFlowDirection, FrequencyUnit
from tests.browser.mobile import PHONE_WIDTHS, assert_fits_phone
from tests.support import WS

pytestmark = [pytest.mark.browser, pytest.mark.db]

W = "/workspaces/{workspace_id}"

# Route (as the OpenAPI schema names it) -> a page to open for it.
SCREENS = {
    W: "/workspaces/{ws}",
    f"{W}/accounts": "/workspaces/{ws}/accounts",
    f"{W}/accounts/new": "/workspaces/{ws}/accounts/new",
    f"{W}/accounts/{{account_id}}/edit": "/workspaces/{ws}/accounts/{tax}/edit",
    f"{W}/cash-flows": "/workspaces/{ws}/cash-flows",
    f"{W}/cash-flows/new": "/workspaces/{ws}/cash-flows/new",
    f"{W}/cash-flows/{{flow_id}}/edit": "/workspaces/{ws}/cash-flows/{flow}/edit",
    f"{W}/cash-flow-categories": "/workspaces/{ws}/cash-flow-categories",
    f"{W}/settings": "/workspaces/{ws}/settings",
    "/welcome": "/welcome",
    "/login": "/login",
}


def html_routes() -> set[str]:
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
    assert html_routes() == set(SCREENS)


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


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("route", sorted(SCREENS))
def test_the_screen_fits(open_page, ids, route, width):
    page = open_page(SCREENS[route].format(**ids), phone=width)
    # A drawer slides up on a phone; measure once it has settled.
    page.wait_for_function(
        "document.getAnimations().every(a => a.playState === 'finished')"
    )
    assert_fits_phone(page)
