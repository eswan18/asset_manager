"""Web tests: real database container plus a signed session cookie."""

from datetime import date
from decimal import Decimal

import pytest
from itsdangerous import URLSafeTimedSerializer

from asset_manager.accounts import create_account
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
