from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_LOCAL_TIME = time(hour=8, minute=1)


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def resolve_scheduled_at(raw: str | None, *, now: datetime | None = None) -> datetime:
    current = now or utc_now()
    if raw is None:
        return current.astimezone(UTC)
    if "T" not in raw:
        local = datetime.combine(date.fromisoformat(raw), DEFAULT_LOCAL_TIME, tzinfo=SHANGHAI)
        return local.astimezone(UTC)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(UTC)
