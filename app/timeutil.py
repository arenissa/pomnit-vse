"""Утилиты работы со временем: часовые пояса, форматирование, хранение в БД."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

_UNITS = (
    ("неделя", "недели", "недель", 7 * 24 * 60),
    ("день", "дня", "дней", 24 * 60),
    ("час", "часа", "часов", 60),
    ("минута", "минуты", "минут", 1),
)


def get_tz(name: str) -> ZoneInfo:
    """Возвращает валидную зону, падая на UTC вместо исключения."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_db(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_db(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def plural(value: int, one: str, few: str, many: str) -> str:
    mod10, mod100 = value % 10, value % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many


def human_delta(td: timedelta) -> str:
    """Короткая человекочитаемая длительность: '2 ч 15 мин'."""
    minutes = int(round(abs(td.total_seconds()) / 60))
    if minutes < 1:
        return "меньше минуты"
    if minutes < 60:
        return f"{minutes} {plural(minutes, 'минуту', 'минуты', 'минут')}"

    parts: list[str] = []
    for one, few, many, unit_minutes in _UNITS:
        if minutes >= unit_minutes:
            count, minutes = divmod(minutes, unit_minutes)
            parts.append(f"{count} {plural(count, one, few, many)}")
        if len(parts) == 2:
            break
    return " ".join(parts)


def format_local(dt: datetime, tz: ZoneInfo) -> str:
    local = dt.astimezone(tz)
    return f"{WEEKDAYS_SHORT[local.weekday()]}, {local:%d.%m.%Y} · {local:%H:%M}"


def deadline_hint(dt: datetime, now: datetime) -> str:
    if dt <= now:
        return f"просрочено на {human_delta(now - dt)}"
    return f"через {human_delta(dt - now)}"


def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def resolve_deadline(year: int, month: int, day: int, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    """Собирает осознанный datetime из локальных компонентов."""
    return datetime(year, month, day, hour, minute, tzinfo=tz).astimezone(timezone.utc)


def shift_to_next_day(dt: datetime) -> datetime:
    return dt + timedelta(days=1)
