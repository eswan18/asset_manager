"""Tests for local_date/today: snapshot dates use a configured timezone."""

from datetime import date, datetime, timezone

from asset_manager.clock import local_date, today
from asset_manager.config import get_settings


def test_local_date_before_midnight_utc_is_still_yesterday_in_chicago():
    now = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)
    assert local_date(now, "America/Chicago") == date(2026, 9, 6)


def test_local_date_after_local_midnight_rolls_over():
    now = datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc)
    assert local_date(now, "America/Chicago") == date(2026, 9, 7)


def test_today_honors_timezone_setting(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Pacific/Kiritimati")
    get_settings.cache_clear()
    try:
        assert today() == local_date(datetime.now(timezone.utc), "Pacific/Kiritimati")
    finally:
        get_settings.cache_clear()
