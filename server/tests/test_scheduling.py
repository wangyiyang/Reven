from datetime import UTC, datetime

from reven.scheduling import resolve_scheduled_at


def test_date_only_defaults_to_0801_shanghai() -> None:
    assert resolve_scheduled_at("2026-08-01") == datetime(2026, 8, 1, 0, 1, tzinfo=UTC)


def test_datetime_uses_explicit_offset() -> None:
    assert resolve_scheduled_at("2026-08-01T09:30:00+08:00") == datetime(2026, 8, 1, 1, 30, tzinfo=UTC)


def test_naive_datetime_interpreted_as_shanghai() -> None:
    assert resolve_scheduled_at("2026-08-01T09:30") == datetime(2026, 8, 1, 1, 30, tzinfo=UTC)


def test_missing_plan_runs_now() -> None:
    now = datetime(2026, 7, 29, 7, 0, tzinfo=UTC)
    assert resolve_scheduled_at(None, now=now) == now
