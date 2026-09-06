"""Web tests: real database container plus a signed session cookie."""

from datetime import date
from decimal import Decimal

import pytest
from itsdangerous import URLSafeTimedSerializer

from asset_manager.accounts import create_account, retire_account
from asset_manager.models import Account, Record, RecordType
from asset_manager.repository import upsert_amounts

SECRET = "test-secret-key"
USER = {"sub": "user-1", "email": "me@example.com", "name": "Me"}


@pytest.fixture
def client(db_connection, db_url, monkeypatch):
    """A TestClient wired to the test container. db_connection handles cleanup."""
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)

    from fastapi.testclient import TestClient

    from asset_manager.config import get_settings
    from asset_manager.web.app import app

    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def login(client) -> None:
    client.cookies.set("session", URLSafeTimedSerializer(SECRET).dumps(USER))


@pytest.mark.db
class TestAuth:
    def test_dashboard_redirects_when_logged_out(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    def test_json_clients_get_401_when_logged_out(self, client):
        response = client.get("/", headers={"Accept": "application/json"})
        assert response.status_code == 401
        assert response.json() == {"error": "Login required"}


def test_is_email_allowed(monkeypatch):
    from asset_manager.web.auth import is_email_allowed

    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    assert is_email_allowed("anyone@example.com")
    assert is_email_allowed(None)

    monkeypatch.setenv("ALLOWED_EMAILS", "Me@Example.com, other@example.com")
    assert is_email_allowed("me@example.com")
    assert is_email_allowed("OTHER@example.com")
    assert not is_email_allowed("stranger@example.com")
    assert not is_email_allowed(None)


@pytest.mark.db
class TestDashboard:
    def test_empty_state(self, client):
        login(client)
        response = client.get("/")
        assert response.status_code == 200
        assert "No data yet" in response.text

    def test_renders_with_data(self, client, db_connection):
        savings = create_account(db_connection, "Savings Account", RecordType.ASSET)
        upsert_amounts(db_connection, date(2026, 9, 1), {savings.id: Decimal("1000")})
        db_connection.commit()
        login(client)
        response = client.get("/")
        assert response.status_code == 200
        assert "Savings Account" in response.text
        assert "$1,000" in response.text


def test_build_chart_html_excludes_retired_from_breakdown():
    from asset_manager.web.charts import build_chart_html

    accounts = [
        Account(id=1, name="Live", type=RecordType.ASSET),
        Account(id=2, name="Old", type=RecordType.ASSET, retired_at=date(2026, 1, 1)),
        Account(id=3, name="Card", type=RecordType.LIABILITY),
    ]
    records = [
        Record(
            date=date(2026, 1, 1),
            account_id=1,
            type=RecordType.ASSET,
            description="Live",
            amount=Decimal("10"),
        ),
        Record(
            date=date(2026, 1, 1),
            account_id=2,
            type=RecordType.ASSET,
            description="Old",
            amount=Decimal("0"),
        ),
        Record(
            date=date(2026, 1, 1),
            account_id=3,
            type=RecordType.LIABILITY,
            description="Card",
            amount=Decimal("4"),
        ),
    ]
    charts, totals, assets_breakdown, liabilities_breakdown = build_chart_html(
        records, accounts
    )
    assert set(charts) == {"assets", "liabilities", "summary"}
    assert totals == {"net_worth": 6.0, "assets": 10.0, "liabilities": 4.0}
    assert assets_breakdown == {"Live": 10.0}
    assert liabilities_breakdown == {"Card": 4.0}


def test_format_percent():
    from asset_manager.web.accounts_routes import format_percent

    assert format_percent(Decimal("0.15")) == "15"
    assert format_percent(Decimal("0.325")) == "32.5"
    assert format_percent(Decimal("0")) == "0"
    assert format_percent(Decimal("1")) == "100"


def test_account_rows_view_model():
    from asset_manager.models import ProportionalFormula
    from asset_manager.web.accounts_routes import account_rows

    schwab = Account(id=1, name="Schwab", type=RecordType.ASSET)
    tax = Account(
        id=2,
        name="Cap Gains Tax",
        type=RecordType.LIABILITY,
        formula=ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("70634")),
        input_ids=[1],
    )
    old = Account(id=3, name="Old", type=RecordType.ASSET, retired_at=date(2026, 1, 1))
    latest = [
        Record(
            date=date(2026, 9, 1),
            account_id=1,
            type=RecordType.ASSET,
            description="Schwab",
            amount=Decimal("163202.77"),
        ),
        Record(
            date=date(2026, 9, 1),
            account_id=2,
            type=RecordType.LIABILITY,
            description="Cap Gains Tax",
            amount=Decimal("13885.32"),
        ),
    ]

    rows = account_rows([schwab, tax, old], latest)

    assert rows[0] == {
        "id": 1,
        "name": "Schwab",
        "type": "asset",
        "computed": False,
        "formula": None,
        "input_ids": [],
        "amount": "163202.77",
        "amount_display": "163,202.77",
        "basis_display": "",
        "retired": False,
        "retired_at": None,
        "formula_text": "",
    }
    assert rows[1]["computed"] is True
    assert rows[1]["formula"] == {
        "kind": "proportional",
        "rate": "0.15",
        "cost_basis": "70634",
    }
    assert rows[1]["basis_display"] == "70,634.00"
    assert rows[1]["formula_text"] == "15% × (Schwab − basis)"
    assert rows[2]["retired"] is True
    assert rows[2]["retired_at"] == "2026-01-01"
    assert rows[2]["amount"] is None
    assert rows[2]["amount_display"] == ""


@pytest.mark.db
class TestAccountsPage:
    def test_empty_state(self, client):
        login(client)
        response = client.get("/accounts")
        assert response.status_code == 200
        assert "No accounts yet" in response.text

    def test_renders_rows_and_embeds_json(self, client, db_connection):
        from asset_manager.models import ProportionalFormula

        schwab = create_account(db_connection, "Schwab Trading", RecordType.ASSET)
        create_account(
            db_connection,
            "Cap Gains Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        old = create_account(db_connection, "Old 401k", RecordType.ASSET)
        retire_account(db_connection, old.id, date(2026, 1, 1))
        upsert_amounts(db_connection, date(2026, 9, 1), {schwab.id: Decimal("1000")})
        db_connection.commit()
        login(client)

        response = client.get("/accounts")

        assert response.status_code == 200
        text = response.text
        assert 'id="accounts-data"' in text
        assert 'value="1,000.00"' in text
        assert "Cap Gains Tax" in text
        assert "Show retired (1)" in text
        assert "September 1, 2026" in text
        assert f'href="/accounts/{schwab.id}/edit"' in text

    def test_redirects_when_logged_out(self, client):
        response = client.get("/accounts", follow_redirects=False)
        assert response.status_code == 302


@pytest.mark.db
class TestSaveSnapshot:
    def test_writes_computed_rows(self, client, db_connection):
        from asset_manager.models import ProportionalFormula
        from asset_manager.repository import get_all_records

        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        tax = create_account(
            db_connection,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        login(client)

        response = client.post(
            "/snapshots",
            json={
                "values": {str(schwab.id): "1000.00"},
                "cost_bases": {str(tax.id): "400.00"},
            },
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        assert response.json() == {"date": date.today().isoformat(), "count": 2}
        rows = {(r.description, r.amount) for r in get_all_records(db_connection)}
        assert rows == {("Schwab", Decimal("1000.00")), ("Tax", Decimal("90.00"))}

    def test_rounds_more_than_two_decimals_half_up_on_the_server(
        self, client, db_connection
    ):
        """The server, not the browser, decides the final cent (ROUND_HALF_UP)."""
        from asset_manager.repository import get_all_records

        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        login(client)

        response = client.post(
            "/snapshots",
            json={"values": {str(schwab.id): "10.005"}, "cost_bases": {}},
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        records = get_all_records(db_connection)
        assert [r.amount for r in records] == [Decimal("10.01")]

    def test_missing_value_returns_400_and_writes_nothing(self, client, db_connection):
        from asset_manager.repository import get_all_records

        create_account(db_connection, "Schwab", RecordType.ASSET)
        create_account(db_connection, "Cash", RecordType.ASSET)
        login(client)

        response = client.post("/snapshots", json={"values": {}, "cost_bases": {}})

        assert response.status_code == 400
        assert "Missing value for" in response.json()["error"]
        assert get_all_records(db_connection) == []

    def test_requires_login(self, client):
        response = client.post(
            "/snapshots", json={"values": {}}, headers={"Accept": "application/json"}
        )
        assert response.status_code == 401
