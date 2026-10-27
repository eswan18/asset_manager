"""Tests for local_date/today: "today" is the date in a given zone."""

from datetime import date, datetime, timezone

from sensibility.clock import default_timezone, local_date, today
from sensibility.config import get_settings


def test_local_date_before_midnight_utc_is_still_yesterday_in_chicago():
    now = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)
    assert local_date(now, "America/Chicago") == date(2026, 9, 6)


def test_local_date_after_local_midnight_rolls_over():
    now = datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc)
    assert local_date(now, "America/Chicago") == date(2026, 9, 7)


def test_today_is_the_date_in_the_given_zone():
    # UTC+14 and UTC-11 are 25 hours apart, so their dates always differ.
    ahead, behind = today("Pacific/Kiritimati"), today("Pacific/Pago_Pago")
    assert ahead == local_date(datetime.now(timezone.utc), "Pacific/Kiritimati")
    assert ahead > behind


def test_default_timezone_comes_from_the_setting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("TIMEZONE", "Pacific/Kiritimati")
    get_settings.cache_clear()
    try:
        assert default_timezone() == "Pacific/Kiritimati"
    finally:
        get_settings.cache_clear()
