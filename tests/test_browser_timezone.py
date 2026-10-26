"""Today is the viewer's day: the browser's zone (the `tz` cookie), or an
explicit `X-Timezone` header from an API client, else the TIMEZONE default."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from asset_manager import clock
from asset_manager.accounts import create_account
from asset_manager.models import RecordType
from asset_manager.repository import get_account, get_all_records, upsert_amounts
from tests.support import WS
from tests.web_support import PAGES, SNAPSHOTS, login

# 06:30 UTC on Oct 27 is still Oct 26 in Los Angeles (23:30) but already
# Oct 27 in Tokyo (15:30) and in Chicago, the default (01:30).
NOW = datetime(2026, 10, 27, 6, 30, tzinfo=timezone.utc)
LA_DAY, TOKYO_DAY = date(2026, 10, 26), date(2026, 10, 27)
# 04:00 UTC on Oct 27 is Oct 26 in Chicago (23:00) but Oct 27 in Tokyo.
EVENING = datetime(2026, 10, 27, 4, 0, tzinfo=timezone.utc)


@pytest.fixture
def at(monkeypatch):
    """Freeze clock.now at the given instant."""

    def freeze(instant: datetime) -> None:
        monkeypatch.setattr(clock, "now", lambda: instant)

    return freeze


@pytest.fixture
def cash(db_connection):
    account = create_account(db_connection, WS, "Cash", RecordType.ASSET)
    db_connection.commit()
    return account


def save_page(client, cash, **kwargs):
    return client.post(
        f"{PAGES}/snapshots", json={"values": {str(cash.id): "5"}}, **kwargs
    )


def save_api(client, cash, **kwargs):
    return client.post(SNAPSHOTS, json={"values": {str(cash.id): "5"}}, **kwargs)


class TestZoneFor:
    def test_explicit_wins_over_cookie(self):
        assert clock.zone_for("Asia/Tokyo", "America/Los_Angeles") == "Asia/Tokyo"

    def test_cookie_when_no_explicit(self):
        assert clock.zone_for(None, "America/Los_Angeles") == "America/Los_Angeles"

    @pytest.mark.parametrize(
        "cookie", [None, "", "Mars/Olympus", "../etc/passwd", "utc", "Etc/Unknown"]
    )
    def test_missing_or_unknown_cookie_falls_back_to_default(self, cookie, monkeypatch):
        monkeypatch.setattr(clock, "default_timezone", lambda: "Pacific/Fiji")
        assert clock.zone_for(None, cookie) == "Pacific/Fiji"

    def test_unknown_cookie_is_ignored_under_explicit(self):
        assert clock.zone_for("Asia/Tokyo", "nope") == "Asia/Tokyo"

    def test_is_known_zone(self):
        assert clock.is_known_zone("America/Chicago")
        assert clock.is_known_zone("UTC")
        assert not clock.is_known_zone("Central")
        assert not clock.is_known_zone("")

    def test_today_uses_now(self, monkeypatch):
        monkeypatch.setattr(clock, "now", lambda: NOW)
        assert clock.today("America/Los_Angeles") == LA_DAY
        assert clock.today("Asia/Tokyo") == TOKYO_DAY


@pytest.mark.db
class TestPageSave:
    @pytest.mark.parametrize(
        "zone, expected", [("America/Los_Angeles", LA_DAY), ("Asia/Tokyo", TOKYO_DAY)]
    )
    def test_cookie_zone_dates_the_save(
        self, client, db_connection, cash, at, zone, expected
    ):
        at(NOW)
        login(client)
        client.cookies.set("tz", zone)
        response = save_page(client, cash)
        assert response.status_code == 200
        assert response.json()["date"] == expected.isoformat()
        assert [r.date for r in get_all_records(db_connection, WS)] == [expected]

    def test_invalid_cookie_falls_back_to_the_default(self, client, cash, at):
        at(EVENING)
        login(client)
        client.cookies.set("tz", "Mars/Olympus")
        assert save_page(client, cash).json()["date"] == "2026-10-26"

    def test_no_cookie_uses_the_default(self, client, cash, at):
        at(EVENING)
        login(client)
        assert save_page(client, cash).json()["date"] == "2026-10-26"

    def test_default_comes_from_the_setting(self, client, cash, at, monkeypatch):
        monkeypatch.setattr(clock, "default_timezone", lambda: "Asia/Tokyo")
        at(EVENING)
        login(client)
        assert save_page(client, cash).json()["date"] == "2026-10-27"


@pytest.mark.db
class TestApiSave:
    def test_cookie_zone_dates_the_save(self, client, cash, at):
        at(NOW)
        login(client)
        client.cookies.set("tz", "America/Los_Angeles")
        assert save_api(client, cash).json()["date"] == LA_DAY.isoformat()

    def test_header_wins_over_cookie(self, client, cash, at):
        at(NOW)
        login(client)
        client.cookies.set("tz", "America/Los_Angeles")
        response = save_api(client, cash, headers={"X-Timezone": "Asia/Tokyo"})
        assert response.json()["date"] == TOKYO_DAY.isoformat()

    def test_header_without_cookie(self, client, cash, at):
        at(EVENING)
        login(client)
        response = save_api(client, cash, headers={"X-Timezone": "Asia/Tokyo"})
        assert response.json()["date"] == "2026-10-27"

    def test_unknown_header_is_a_400_and_saves_nothing(
        self, client, db_connection, cash, at
    ):
        at(NOW)
        login(client)
        response = save_api(client, cash, headers={"X-Timezone": "Mars/Olympus"})
        assert response.status_code == 400
        assert response.json() == {"error": "'Mars/Olympus' is not a known time zone"}
        assert get_all_records(db_connection, WS) == []

    def test_no_cookie_uses_the_default(self, client, cash, at):
        at(EVENING)
        login(client)
        assert save_api(client, cash).json()["date"] == "2026-10-26"


@pytest.mark.db
class TestRetire:
    @pytest.mark.parametrize(
        "zone, expected", [("America/Los_Angeles", LA_DAY), ("Asia/Tokyo", TOKYO_DAY)]
    )
    def test_retirement_is_dated_in_the_cookie_zone(
        self, client, db_connection, cash, at, zone, expected
    ):
        at(NOW)
        login(client)
        client.cookies.set("tz", zone)
        client.post(f"{PAGES}/accounts/{cash.id}/retire", follow_redirects=False)
        loaded = get_account(db_connection, WS, cash.id)
        assert loaded is not None and loaded.retired_at == expected

    def test_retirement_without_cookie_uses_the_default(
        self, client, db_connection, cash, at
    ):
        at(EVENING)
        login(client)
        client.post(f"{PAGES}/accounts/{cash.id}/retire", follow_redirects=False)
        loaded = get_account(db_connection, WS, cash.id)
        assert loaded is not None and loaded.retired_at == date(2026, 10, 26)


@pytest.mark.db
class TestSnapshotLine:
    @pytest.fixture
    def saved_on_la_day(self, db_connection, cash):
        upsert_amounts(db_connection, WS, LA_DAY, {cash.id: Decimal("1")})
        db_connection.commit()

    def test_accounts_page_line_uses_the_cookie_zone(self, client, saved_on_la_day, at):
        at(NOW)
        login(client)
        client.cookies.set("tz", "America/Los_Angeles")
        text = client.get(f"{PAGES}/accounts").text
        assert "today&#39;s snapshot, Oct 26, 2026. Last saved today" in text
        client.cookies.set("tz", "Asia/Tokyo")
        text = client.get(f"{PAGES}/accounts").text
        assert "today&#39;s snapshot, Oct 27, 2026. Last saved Oct 26." in text

    def test_account_drawer_line_uses_the_cookie_zone(
        self, client, cash, saved_on_la_day, at
    ):
        at(NOW)
        login(client)
        client.cookies.set("tz", "America/Los_Angeles")
        text = client.get(f"{PAGES}/accounts/{cash.id}/edit").text
        assert "today&#39;s snapshot, Oct 26, 2026. Last saved today" in text
        client.cookies.set("tz", "Asia/Tokyo")
        text = client.get(f"{PAGES}/accounts/new").text
        assert "today&#39;s snapshot, Oct 27, 2026. Last saved Oct 26." in text


@pytest.mark.db
def test_every_page_stores_the_browser_zone_in_a_cookie(client):
    login(client)
    text = client.get(f"{PAGES}/accounts").text
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in text
    assert 'document.cookie = "tz=" + encodeURIComponent(' in text
    assert "path=/" in text and "SameSite=Lax" in text and "max-age=" in text
