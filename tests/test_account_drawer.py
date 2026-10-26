"""The account form: a drawer over the Accounts page (board Account form Q).

Every state the form handles: new (either type), edit plain, edit computed,
the retire warning and blocker, retired accounts, validation errors, and
viewers. Each one renders the Accounts page underneath with the drawer open.
"""

import re
from datetime import date
from decimal import Decimal

import pytest

from asset_manager.accounts import create_account, retire_account
from asset_manager.models import ProportionalFormula, RecordType
from asset_manager.repository import get_account, upsert_amounts
from asset_manager.web.accounts_routes import formula_preview
from tests.support import WS
from tests.web_support import PAGES, STRANGER, add_user, login, session_for

ASSET, LIABILITY = RecordType.ASSET, RecordType.LIABILITY
ACCOUNTS_PAGE = f"{PAGES}/accounts"


def drawer(text: str) -> str:
    """The drawer's markup alone."""
    start = text.index('<aside class="drawer')
    return text[start : text.index("</aside>", start)]


def behind(text: str) -> str:
    """Everything but the drawer: the shell and the Accounts page."""
    start = text.index('<aside class="drawer')
    return text[:start] + text[text.index("</aside>", start) :]


@pytest.fixture
def tax_setup(db_connection):
    """Schwab (an input), Fidelity (not one) and a computed tax liability,
    with one snapshot."""
    schwab = create_account(db_connection, WS, "Schwab", ASSET)
    fidelity = create_account(db_connection, WS, "Fidelity", ASSET)
    tax = create_account(
        db_connection,
        WS,
        "Cap gains tax",
        LIABILITY,
        ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("82386.74")),
        [schwab.id],
    )
    upsert_amounts(
        db_connection,
        WS,
        date(2026, 9, 27),
        {
            schwab.id: Decimal("179265.00"),
            fidelity.id: Decimal("1000.00"),
            tax.id: Decimal("14531.74"),
        },
    )
    db_connection.commit()
    return schwab, fidelity, tax


# --- the computed-value line ------------------------------------------------


class TestFormulaPreview:
    def test_rate_times_inputs_less_basis(self):
        preview = formula_preview("15", "82,386.74", [1], {1: Decimal("179265.00")})
        assert preview == {
            "text": "15% × ($179,265 − $82,387)",
            "value": "$14,531.74",
        }

    def test_sums_every_input(self):
        amounts = {1: Decimal("100"), 2: Decimal("50.50")}
        preview = formula_preview("10", "", [1, 2], amounts)
        assert preview == {"text": "10% × ($151 − $0)", "value": "$15.05"}

    def test_rounds_half_up_like_a_save(self):
        # 0.5 × 0.05 = 0.025: a save stores 0.03, so the preview does too.
        preview = formula_preview("50", "", [1], {1: Decimal("0.05")})
        assert preview is not None and preview["value"] == "$0.03"

    def test_below_basis_is_negative(self):
        preview = formula_preview("10", "500", [1], {1: Decimal("100")})
        assert preview == {"text": "10% × ($100 − $500)", "value": "-$40.00"}

    def test_negative_inputs_read_as_negative_dollars(self):
        preview = formula_preview("10", "", [1], {1: Decimal("-50")})
        assert preview == {"text": "10% × (-$50 − $0)", "value": "-$5.00"}

    def test_an_input_with_no_saved_amount_has_no_value(self):
        preview = formula_preview("15", "", [1, 2], {1: Decimal("5")})
        assert preview is not None and preview["value"] == "—"

    @pytest.mark.parametrize(
        "rate, basis, inputs",
        [
            ("", "", [1]),
            ("abc", "", [1]),
            ("-5", "", [1]),
            ("15", "x", [1]),
            ("15", "", []),
        ],
    )
    def test_nothing_to_show(self, rate, basis, inputs):
        assert formula_preview(rate, basis, inputs, {1: Decimal("5")}) is None


# --- the drawer over the Accounts page ----------------------------------------


@pytest.mark.db
class TestDrawerShell:
    def test_accounts_page_has_no_drawer(self, client, tax_setup):
        login(client)
        text = client.get(ACCOUNTS_PAGE).text
        assert "<aside" not in text
        assert " inert" not in text
        assert "drawer-open" not in text

    def test_edit_renders_the_accounts_page_underneath(self, client, tax_setup):
        schwab, fidelity, tax = tax_setup
        login(client)
        text = client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text
        page = behind(text)
        # The real Accounts page: its rows, its staged-edit script and save bar.
        assert f'href="{PAGES}/accounts/{schwab.id}/edit">Schwab</a>' in page
        assert 'id="accounts-data"' in page
        assert "asset-manager:staged-edits" in page
        assert 'id="save-button"' in page
        # Shown with the Accounts tab active, its picker on Accounts.
        assert 'href="/workspaces/1/accounts" aria-current="page"' in page

    def test_page_behind_is_inert_and_the_body_locked(self, client, tax_setup):
        tax = tax_setup[2]
        login(client)
        text = client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text
        assert '<header class="shell-header" inert>' in text
        assert '<main class="container" inert>' in text
        assert '<body class="drawer-open">' in text
        assert 'class="scrim"' in text

    def test_drawer_is_a_labelled_modal_dialog(self, client, tax_setup):
        tax = tax_setup[2]
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text)
        assert 'role="dialog"' in d
        assert 'aria-modal="true"' in d
        assert 'aria-labelledby="drawer-title"' in d
        assert '<h1 id="drawer-title">Cap gains tax</h1>' in d

    def test_close_and_cancel_go_back_to_accounts(self, client, tax_setup):
        tax = tax_setup[2]
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text)
        assert f'class="drawer-close" href="{ACCOUNTS_PAGE}" aria-label="Close"' in d
        assert f'<a class="btn btn-outline" href="{ACCOUNTS_PAGE}">Cancel</a>' in d
        # Save sits in the pinned footer, outside the form it submits.
        assert (
            '<button type="submit" class="btn btn-primary" form="account-form">Save</button>'
            in d
        )

    def test_escape_closes_and_focus_starts_in_the_drawer(self, client, tax_setup):
        tax = tax_setup[2]
        login(client)
        text = client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text
        assert "event.key === 'Escape'" in text
        assert re.search(r'<input[^>]*name="name"[^>]*autofocus', drawer(text))

    def test_title_names_the_account(self, client, tax_setup):
        tax = tax_setup[2]
        login(client)
        text = client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text
        assert "<title>Cap gains tax · Test · " in text


@pytest.mark.db
class TestNewAccount:
    def test_new_asset_by_default(self, client, db_connection):
        login(client)
        response = client.get(f"{ACCOUNTS_PAGE}/new")
        assert response.status_code == 200
        d = drawer(response.text)
        assert 'class="drawer section-asset"' in d
        assert '<span class="drawer-eyebrow">New account</span>' in d
        assert '<h1 id="drawer-title">New asset</h1>' in d
        assert re.search(r'name="type" value="asset"\s+checked', d)
        assert not re.search(r'name="type" value="liability"\s+checked', d)
        assert f'action="{ACCOUNTS_PAGE}"' in d

    def test_new_liability_from_the_query(self, client, db_connection):
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/new?type=liability").text)
        assert 'class="drawer section-liability"' in d
        assert '<h1 id="drawer-title">New liability</h1>' in d
        assert re.search(r'name="type" value="liability"\s+checked', d)

    def test_an_unknown_type_falls_back_to_asset(self, client, db_connection):
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/new?type=boat").text)
        assert 'class="drawer section-asset"' in d

    def test_new_has_no_history_or_retire(self, client, tax_setup):
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/new").text)
        assert "History" not in d
        assert "/retire" not in d
        assert "/unretire" not in d

    def test_formula_fields_start_hidden_and_list_plain_inputs(self, client, tax_setup):
        schwab, fidelity, tax = tax_setup
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/new").text)
        assert '<div id="formula-fields" hidden>' in d
        assert re.search(r'<input type="checkbox" name="computed" id="computed"\s*>', d)
        assert f'name="input_ids" value="{schwab.id}"' in d
        assert f'name="input_ids" value="{fidelity.id}"' in d
        # A computed account is never an input.
        assert f'name="input_ids" value="{tax.id}"' not in d

    def test_inputs_sit_under_their_type(self, client, db_connection):
        schwab = create_account(db_connection, WS, "Schwab", ASSET)
        visa = create_account(db_connection, WS, "Visa", LIABILITY)
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/new").text)
        assets = d.index('<span class="pill-group">Assets</span>')
        liabilities = d.index('<span class="pill-group">Liabilities</span>')
        assert assets < d.index(f'value="{schwab.id}"') < liabilities
        assert liabilities < d.index(f'value="{visa.id}"')
        assert d.count('name="input_ids"') == 2

    def test_one_type_of_input_needs_no_subheading(self, client, db_connection):
        create_account(db_connection, WS, "Schwab", ASSET)
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/new").text)
        assert 'class="pill-group"' not in d

    def test_no_candidates_says_so(self, client, db_connection):
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/new").text)
        assert "No plain, active accounts to use as inputs yet." in d

    def test_new_over_an_empty_accounts_page(self, client, db_connection):
        login(client)
        text = client.get(f"{ACCOUNTS_PAGE}/new").text
        assert "No accounts yet" in behind(text)
        assert 'role="dialog"' in text


@pytest.mark.db
class TestEditComputed:
    def test_header_carries_the_type_and_name(self, client, tax_setup):
        tax = tax_setup[2]
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text)
        assert 'class="drawer section-liability"' in d
        assert '<span class="drawer-eyebrow">Edit liability</span>' in d
        # The type is fixed once created: no type choice.
        assert 'name="type"' not in d
        assert f'action="{ACCOUNTS_PAGE}/{tax.id}"' in d

    def test_formula_fields_prefilled_and_shown(self, client, tax_setup):
        schwab, fidelity, tax = tax_setup
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text)
        assert '<div id="formula-fields">' in d
        assert re.search(r'name="computed" id="computed"\s*checked', d)
        assert 'name="rate_percent" value="15"' in d
        assert 'name="cost_basis" value="82,386.74"' in d
        assert re.search(rf'name="input_ids" value="{schwab.id}"[^>]*checked', d)
        assert not re.search(rf'name="input_ids" value="{fidelity.id}"[^>]*checked', d)

    def test_inputs_carry_their_saved_amounts_for_the_live_line(
        self, client, tax_setup
    ):
        schwab = tax_setup[0]
        tax = tax_setup[2]
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text)
        assert re.search(
            rf'name="input_ids" value="{schwab.id}" data-amount="179265.00"', d
        )

    def test_computed_value_line(self, client, tax_setup):
        tax = tax_setup[2]
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text)
        assert '<span id="formula-text">15% × ($179,265 − $82,387)</span>' in d
        assert '<strong id="formula-value">$14,531.74</strong>' in d

    def test_history_is_collapsed_newest_first(self, client, db_connection, tax_setup):
        schwab, _, tax = tax_setup
        upsert_amounts(
            db_connection, WS, date(2026, 8, 28), {tax.id: Decimal("14289.49")}
        )
        db_connection.commit()
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text)
        assert "<details" in d and "<details open" not in d
        assert "History (2 snapshots)" in d
        assert d.index("Sep 27, 2026") < d.index("Aug 28, 2026")
        assert "$14,531.74</span>" in d and "$14,289.49</span>" in d

    def test_retire_warning_with_retire_anyway(self, client, tax_setup):
        tax = tax_setup[2]
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit").text)
        assert "Last saved at $14,531.74 on September 27, 2026" in d
        assert f'action="{ACCOUNTS_PAGE}/{tax.id}/retire"' in d
        assert (
            '<button type="submit" class="btn btn-danger-outline">Retire anyway</button>'
            in d
        )


@pytest.mark.db
class TestEditPlain:
    def test_formula_fields_hidden(self, client, tax_setup):
        fidelity = tax_setup[1]
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{fidelity.id}/edit").text)
        assert '<span class="drawer-eyebrow">Edit asset</span>' in d
        assert 'class="drawer section-asset"' in d
        assert '<div id="formula-fields" hidden>' in d
        assert re.search(r'name="computed" id="computed"\s*>', d)
        # Never its own input.
        assert f'name="input_ids" value="{fidelity.id}"' not in d

    def test_history_singular(self, client, tax_setup):
        fidelity = tax_setup[1]
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{fidelity.id}/edit").text)
        assert "History (1 snapshot)" in d

    def test_history_empty_state(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", ASSET)
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{cash.id}/edit").text)
        assert "History (no snapshots)" in d
        assert "No snapshots yet" in d

    def test_plain_retire_without_a_warning(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", ASSET)
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{cash.id}/edit").text)
        assert "Retiring hides this account" in d
        assert (
            '<button type="submit" class="btn btn-danger-outline">Retire</button>' in d
        )
        assert "Retire anyway" not in d

    def test_retire_blocker_says_why_and_offers_no_button(self, client, tax_setup):
        schwab = tax_setup[0]
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{schwab.id}/edit").text)
        assert "Schwab is an input to Cap gains tax" in d
        assert "/retire" not in d
        assert "Retire anyway" not in d

    def test_retired_offers_unretire(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", ASSET)
        retire_account(db_connection, WS, cash.id, date(2026, 9, 1))
        login(client)
        d = drawer(client.get(f"{ACCOUNTS_PAGE}/{cash.id}/edit").text)
        assert "Retired Sep 1, 2026." in d
        assert f'action="{ACCOUNTS_PAGE}/{cash.id}/unretire"' in d
        assert '<button type="submit" class="btn btn-outline">Unretire</button>' in d
        assert f"{cash.id}/retire" not in d


@pytest.mark.db
class TestValidationErrors:
    def test_create_error_rerenders_in_the_drawer_with_input(self, client, tax_setup):
        schwab = tax_setup[0]
        login(client)
        response = client.post(
            ACCOUNTS_PAGE,
            data={
                "name": "Cap gains tax",
                "type": "liability",
                "category": "tax_liability",
                "computed": "on",
                "rate_percent": "20",
                "cost_basis": "1,000",
                "input_ids": [str(schwab.id)],
            },
        )
        assert response.status_code == 400
        d = drawer(response.text)
        assert 'class="drawer-error" role="alert"' in d
        assert "already exists" in d
        # Not in the page behind the scrim.
        assert '<div class="error">' not in behind(response.text)
        assert 'name="name" value="Cap gains tax"' in d
        assert re.search(r'name="type" value="liability"\s+checked', d)
        assert '<option value="tax_liability" selected>' in d
        assert re.search(r'name="computed" id="computed"\s*checked', d)
        assert '<div id="formula-fields">' in d
        assert 'name="rate_percent" value="20"' in d
        assert 'name="cost_basis" value="1,000"' in d
        assert re.search(rf'name="input_ids" value="{schwab.id}"[^>]*checked', d)
        # Still over the Accounts page.
        assert 'id="accounts-data"' in behind(response.text)

    def test_update_error_rerenders_in_the_drawer_with_input(self, client, tax_setup):
        schwab, fidelity, tax = tax_setup
        login(client)
        response = client.post(
            f"{ACCOUNTS_PAGE}/{tax.id}",
            data={
                "name": "Renamed",
                "computed": "on",
                "rate_percent": "abc",
                "input_ids": [str(fidelity.id)],
            },
        )
        assert response.status_code == 400
        d = drawer(response.text)
        assert "Rate must be a number" in d
        assert 'name="name" value="Renamed"' in d
        assert 'name="rate_percent" value="abc"' in d
        assert re.search(rf'name="input_ids" value="{fidelity.id}"[^>]*checked', d)
        assert not re.search(rf'name="input_ids" value="{schwab.id}"[^>]*checked', d)
        # The rest of the edit drawer is still there: header, history, retire.
        assert '<h1 id="drawer-title">Cap gains tax</h1>' in d
        assert "History (1 snapshot)" in d
        assert f'action="{ACCOUNTS_PAGE}/{tax.id}/retire"' in d

    def test_update_error_writes_nothing(self, client, db_connection, tax_setup):
        tax = tax_setup[2]
        login(client)
        client.post(
            f"{ACCOUNTS_PAGE}/{tax.id}",
            data={"name": "Renamed", "computed": "on", "rate_percent": "abc"},
        )
        db_connection.rollback()
        loaded = get_account(db_connection, WS, tax.id)
        assert loaded is not None and loaded.name == "Cap gains tax"

    def test_an_unchecked_computed_box_hides_the_fields_again(self, client):
        login(client)
        response = client.post(
            ACCOUNTS_PAGE, data={"name": "", "type": "asset", "rate_percent": "5"}
        )
        assert response.status_code == 400
        d = drawer(response.text)
        assert '<div id="formula-fields" hidden>' in d


@pytest.mark.db
class TestViewer:
    """Viewers see the same form as today: the drawer renders, and its writes
    are refused (403) on submit."""

    def test_viewer_sees_the_edit_drawer(self, client, db_connection, tax_setup):
        tax = tax_setup[2]
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)
        response = client.get(f"{ACCOUNTS_PAGE}/{tax.id}/edit")
        assert response.status_code == 200
        assert '<h1 id="drawer-title">Cap gains tax</h1>' in drawer(response.text)
        assert (
            client.post(f"{ACCOUNTS_PAGE}/{tax.id}", data={"name": "X"}).status_code
            == 403
        )

    def test_viewer_cannot_open_the_new_drawer(self, client, db_connection):
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)
        assert client.get(f"{ACCOUNTS_PAGE}/new").status_code == 403
