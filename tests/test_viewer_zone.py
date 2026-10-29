"""Today is the viewer's day: the zone an `X-Timezone` header names (the React
app sends the browser's on every request), else the TIMEZONE default."""

from datetime import date, datetime, timezone

import pytest

from sensibility import clock
from sensibility.accounts import create_account
from sensibility.models import RecordType
from sensibility.repository import get_account, get_all_records
from tests.support import WS
from tests.web_support import ACCOUNTS, SNAPSHOTS, login

# Far from the real date, so a clock that ignores clock.now cannot pass.
# 06:30 UTC on Jan 15 is still Jan 14 in Los Angeles (22:30) but already
# Jan 15 in Tokyo (15:30) and in Chicago, the default (00:30).
NOW = datetime(2031, 1, 15, 6, 30, tzinfo=timezone.utc)
LA_DAY, TOKYO_DAY = date(2031, 1, 14), date(2031, 1, 15)
# 04:00 UTC on Jan 15 is Jan 14 in Chicago (22:00) but Jan 15 in Tokyo.
EVENING = datetime(2031, 1, 15, 4, 0, tzinfo=timezone.utc)


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


def save(client, cash, **kwargs):
    return client.post(SNAPSHOTS, json={"values": {str(cash.id): "5"}}, **kwargs)


class TestClock:
    def test_is_known_zone(self):
        assert clock.is_known_zone("America/Chicago")
        assert clock.is_known_zone("UTC")
        for zone in (
            "Central",
            "",
            "Mars/Olympus",
            "../etc/passwd",
            "utc",
            "Etc/Unknown",
        ):
            assert not clock.is_known_zone(zone), zone

    def test_today_uses_now(self, monkeypatch):
        monkeypatch.setattr(clock, "now", lambda: NOW)
        assert clock.today("America/Los_Angeles") == LA_DAY
        assert clock.today("Asia/Tokyo") == TOKYO_DAY


@pytest.mark.db
class TestSave:
    @pytest.mark.parametrize(
        "zone, expected", [("America/Los_Angeles", LA_DAY), ("Asia/Tokyo", TOKYO_DAY)]
    )
    def test_the_header_dates_the_save(
        self, client, db_connection, cash, at, zone, expected
    ):
        at(NOW)
        login(client)
        response = save(client, cash, headers={"X-Timezone": zone})
        assert response.status_code == 200
        assert response.json()["date"] == expected.isoformat()
        assert [r.date for r in get_all_records(db_connection, WS)] == [expected]

    @pytest.mark.parametrize("zone", ["Mars/Olympus", "../etc/passwd", ""])
    def test_an_unknown_header_is_a_400_and_saves_nothing(
        self, client, db_connection, cash, at, zone
    ):
        at(NOW)
        login(client)
        response = save(client, cash, headers={"X-Timezone": zone})
        assert response.status_code == 400
        assert response.json() == {"error": f"{zone!r} is not a known time zone"}
        assert get_all_records(db_connection, WS) == []

    def test_no_header_uses_the_default(self, client, cash, at):
        at(EVENING)
        login(client)
        assert save(client, cash).json()["date"] == "2031-01-14"

    def test_the_default_comes_from_the_setting(self, client, cash, at, monkeypatch):
        monkeypatch.setenv("TIMEZONE", "Asia/Tokyo")
        clock.get_settings.cache_clear()
        at(EVENING)
        login(client)
        assert save(client, cash).json()["date"] == "2031-01-15"

    def test_a_leftover_tz_cookie_is_ignored(self, client, cash, at):
        """The Jinja pages stored the zone in a `tz` cookie; browsers keep it
        for a year, but only the header counts now."""
        at(NOW)
        login(client)
        client.cookies.set("tz", "America/Los_Angeles")
        assert save(client, cash).json()["date"] == TOKYO_DAY.isoformat()


@pytest.mark.db
class TestRetire:
    @pytest.mark.parametrize(
        "zone, expected", [("America/Los_Angeles", LA_DAY), ("Asia/Tokyo", TOKYO_DAY)]
    )
    def test_retirement_is_dated_in_the_header_zone(
        self, client, db_connection, cash, at, zone, expected
    ):
        at(NOW)
        login(client)
        response = client.post(
            f"{ACCOUNTS}/{cash.id}/retire", headers={"X-Timezone": zone}
        )
        assert response.json()["retired_at"] == expected.isoformat()
        loaded = get_account(db_connection, WS, cash.id)
        assert loaded is not None and loaded.retired_at == expected

    def test_retirement_without_a_header_uses_the_default(
        self, client, db_connection, cash, at
    ):
        at(EVENING)
        login(client)
        assert client.post(f"{ACCOUNTS}/{cash.id}/retire").status_code == 200
        loaded = get_account(db_connection, WS, cash.id)
        assert loaded is not None and loaded.retired_at == date(2031, 1, 14)


@pytest.mark.db
def test_the_overview_is_as_of_the_viewers_today(client, cash, at):
    at(NOW)
    login(client)
    overview = f"{ACCOUNTS}/overview"
    assert (
        client.get(overview, headers={"X-Timezone": "America/Los_Angeles"}).json()[
            "as_of"
        ]
        == LA_DAY.isoformat()
    )
    assert client.get(overview).json()["as_of"] == TOKYO_DAY.isoformat()
